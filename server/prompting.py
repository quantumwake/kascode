"""Translate Anthropic-style messages <-> the model's native chat dialect.

Two dialects are supported, auto-detected from the chat template:

  - GemmaDialect (gemma-4): <|channel>thought / <|tool_call>call:name{...}
    with Gemma's custom argument serialization; supports raw-stream
    continuation (its rotating caches can't be trimmed, so we keep the raw
    token stream append-only).
  - QwenDialect (qwen3.x ChatML): <think>...</think> blocks (pre-opened by
    the generation prompt) and XML-ish tool calls
    <tool_call><function=name><parameter=key>value</parameter>...; arguments
    arrive as raw strings and are coerced via the tool's input_schema. No
    continuation memo needed — Qwen's caches are all trimmable, so plain
    prefix-trim reuse in the engine handles cache hits.

Original Gemma-4 notes:

Gemma-4's chat template natively supports tools, tool calls, tool responses,
and a thinking channel, so we feed it OpenAI-shaped structures and let
`apply_chat_template` do the rendering:

  - tools         -> [{"type": "function", "function": {...}}]      (tools= kwarg)
  - tool_use      -> assistant message {"tool_calls": [...]}
  - tool_result   -> {"role": "tool", "tool_call_id": ..., "content": ...}
  - thinking      -> enable_thinking=True / "reasoning" field on assistant turns

On the way out the model emits:

  <|channel>thought ...reasoning... <channel|>          -> Anthropic thinking block
  <|tool_call>call:name{args}<tool_call|>               -> Anthropic tool_use block
  plain text                                            -> Anthropic text block

where {args} uses Gemma's serialization: strings are <|"|>-quoted, numbers and
booleans bare, dicts/lists like JSON without quoted keys at the call level.
"""

import json
import re
import uuid
from typing import Any, Iterator

from .schema import Message, TextBlock, ThinkingBlock, ToolDef, ToolResultBlock, ToolUseBlock

CH_OPEN = "<|channel>"
CH_CLOSE = "<channel|>"
TC_OPEN = "<|tool_call>"
TC_CLOSE = "<tool_call|>"
QUOTE = '<|"|>'

Event = tuple[str, Any]  # ("text", str) | ("thinking", str) | ("tool_use", dict)

# Schemas map for argument coercion: {tool_name: {param: json_schema_type}}
Schemas = dict[str, dict[str, str]]


class GemmaDialect:
    name = "gemma"
    supports_continuation = True
    # keep reasoning in re-renders so they can byte-match the raw stream
    template_kwargs = {"preserve_thinking": True}
    # state transitions out of plain text
    text_markers = {CH_OPEN: "think_header", TC_OPEN: "tool_call"}
    think_close = CH_CLOSE
    tool_close = TC_CLOSE

    def initial_state(self, thinking_enabled: bool) -> str:
        return "text"

    def continuation_tail(
        self, results: list[tuple[str, str]], texts: list[str], thinking: bool
    ) -> str | None:
        """Wire bytes for a new user turn appended to the raw cached stream.

        Gemma stops on <eos>/<turn|>/<|tool_response>, all withheld from the
        cache — so after tool calls the tail starts directly at
        <|tool_response>, while a text turn supplies the <turn|> closure.
        """
        parts = [render_tool_response(name, content) for name, content in results]
        if texts:
            joined = "\n\n".join(texts).strip()
            if not joined:
                return None
            if not results:
                parts.append("<turn|>\n")
            parts.append(f"<|turn>user\n{joined}<turn|>\n<|turn>model\n")
            if not thinking:
                parts.append("<|channel>thought\n<channel|>")
        return "".join(parts) or None

    def assistant_entry(self, texts: list[str], reasoning: list[str], tool_calls: list[dict]) -> dict:
        entry: dict[str, Any] = {"role": "assistant", "content": "\n\n".join(texts)}
        if reasoning:
            entry["reasoning"] = "\n\n".join(reasoning)
        if tool_calls:
            entry["tool_calls"] = tool_calls
        return entry

    def parse_tool_body(self, body: str, schemas: Schemas | None) -> dict:
        return parse_tool_call_body(body)

    def wrap_failed_call(self, body: str) -> str:
        return f"{TC_OPEN}{body}{TC_CLOSE}"


class QwenDialect:
    name = "qwen-xml"
    # Qwen3.5/3.6 hybrid models put untrimmable ArraysCache (linear-attention
    # state) on most layers, so divergence = full reset — same constraint as
    # Gemma's rotating caches; the raw-stream continuation memo fixes it.
    supports_continuation = True
    template_kwargs = {"preserve_thinking": True}
    text_markers = {"<think>": "think", "<tool_call>": "tool_call"}
    think_close = "</think>"
    tool_close = "</tool_call>"

    def continuation_tail(
        self, results: list[tuple[str, str]], texts: list[str], thinking: bool
    ) -> str | None:
        """ChatML wire bytes; the withheld stop token is <|im_end|>."""
        parts = ["<|im_end|>\n"]
        if results:
            parts.append("<|im_start|>user")
            for _name, content in results:
                parts.append(f"\n<tool_response>\n{content.strip()}\n</tool_response>")
            parts.append("<|im_end|>\n")
        if texts:
            joined = "\n\n".join(texts).strip()
            if not joined:
                return None
            parts.append(f"<|im_start|>user\n{joined}<|im_end|>\n")
        parts.append("<|im_start|>assistant\n")
        parts.append("<think>\n" if thinking else "<think>\n\n</think>\n\n")
        return "".join(parts)

    def initial_state(self, thinking_enabled: bool) -> str:
        # the generation prompt itself ends with "<think>\n" when thinking is
        # on, so the model starts mid-thought without emitting an opener
        return "think" if thinking_enabled else "text"

    def assistant_entry(self, texts: list[str], reasoning: list[str], tool_calls: list[dict]) -> dict:
        content = "\n\n".join(texts)
        if reasoning:
            content = "<think>\n" + "\n\n".join(reasoning) + "\n</think>\n\n" + content
        entry: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        return entry

    def parse_tool_body(self, body: str, schemas: Schemas | None) -> dict:
        m = re.search(r"<function=([^>\n]+)>", body)
        if m is None:
            raise ValueError("no <function=...> in tool call")
        name = m.group(1).strip()
        types = (schemas or {}).get(name, {})
        args: dict[str, Any] = {}
        for pm in re.finditer(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", body, re.S):
            key = pm.group(1).strip()
            args[key] = _coerce(pm.group(2), types.get(key))
        return {"id": new_tool_use_id(), "name": name, "input": args}

    def wrap_failed_call(self, body: str) -> str:
        return f"<tool_call>{body}</tool_call>"


def _coerce(value: str, schema_type: str | None) -> Any:
    """Qwen parameters arrive as raw text; coerce by the declared schema type."""
    try:
        if schema_type == "integer":
            return int(value.strip())
        if schema_type == "number":
            return float(value.strip())
        if schema_type == "boolean":
            return value.strip().lower() in ("true", "1", "yes")
        if schema_type in ("array", "object"):
            return json.loads(value)
    except (ValueError, json.JSONDecodeError):
        pass  # fall through: hand the raw string to the tool
    return value


def detect_dialect(chat_template: str | None):
    template = chat_template or ""
    if "<function=" in template or "<|im_start|>" in template:
        return QwenDialect()
    return GemmaDialect()  # default; gemma markers simply won't fire elsewhere


def new_tool_use_id() -> str:
    return "toolu_" + uuid.uuid4().hex[:24]


# --------------------------------------------------------------------------
# Request -> chat messages + tools for apply_chat_template
# --------------------------------------------------------------------------


def _system_text(system: str | list[dict[str, Any]] | None) -> str:
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if b.get("type") == "text")


def build_system(
    system: str | list[dict[str, Any]] | None,
    tool_choice: dict[str, Any] | None,
) -> str:
    parts = []
    base = _system_text(system)
    if base:
        parts.append(base)
    choice_type = (tool_choice or {}).get("type")
    if choice_type == "any":
        parts.append("You MUST call one of the available tools in this response.")
    elif choice_type == "tool":
        parts.append(f"You MUST call the tool `{tool_choice['name']}` in this response.")
    return "\n\n".join(parts)


def tools_payload(tools: list[ToolDef]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _tool_result_text(block: ToolResultBlock) -> str:
    content = block.content
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
    text = content or ""
    if block.is_error:
        text = f"ERROR: {text}"
    return text


def to_chat_messages(
    messages: list[Message],
    system: str | list[dict[str, Any]] | None,
    tool_choice: dict[str, Any] | None,
    dialect=None,
) -> list[dict[str, Any]]:
    dialect = dialect or GemmaDialect()
    chat: list[dict[str, Any]] = []
    sys_text = build_system(system, tool_choice)
    if sys_text:
        chat.append({"role": "system", "content": sys_text})

    for msg in messages:
        if isinstance(msg.content, str):
            blocks: list[Any] = [TextBlock(text=msg.content)]
        else:
            blocks = list(msg.content)

        if msg.role == "assistant":
            texts, reasoning, tool_calls = [], [], []
            for b in blocks:
                if isinstance(b, TextBlock):
                    texts.append(b.text)
                elif isinstance(b, ThinkingBlock):
                    reasoning.append(b.thinking)
                elif isinstance(b, ToolUseBlock):
                    tool_calls.append(
                        {
                            "id": b.id,
                            "type": "function",
                            "function": {"name": b.name, "arguments": b.input},
                        }
                    )
            chat.append(dialect.assistant_entry(texts, reasoning, tool_calls))
        else:
            # Tool results become role:"tool" messages (the template forward-scans
            # them from the preceding assistant tool_calls turn); remaining text
            # becomes a normal user message.
            texts = []
            for b in blocks:
                if isinstance(b, ToolResultBlock):
                    chat.append(
                        {
                            "role": "tool",
                            "tool_call_id": b.tool_use_id,
                            "content": _tool_result_text(b),
                        }
                    )
                elif isinstance(b, TextBlock):
                    texts.append(b.text)
            if texts:
                text = "\n\n".join(texts)
                if chat and chat[-1]["role"] == "user":
                    chat[-1]["content"] += "\n\n" + text
                else:
                    chat.append({"role": "user", "content": text})
    return chat


# --------------------------------------------------------------------------
# Gemma tool-call argument syntax -> python objects
# --------------------------------------------------------------------------


def _parse_value(s: str, i: int) -> tuple[Any, int]:
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    if s.startswith(QUOTE, i):
        j = s.find(QUOTE, i + len(QUOTE))
        if j == -1:
            raise ValueError("unterminated string")
        return s[i + len(QUOTE) : j], j + len(QUOTE)
    if i < len(s) and s[i] == "{":
        obj: dict[str, Any] = {}
        i += 1
        while True:
            while i < len(s) and s[i] in " \t\n\r,":
                i += 1
            if i >= len(s):
                raise ValueError("unterminated object")
            if s[i] == "}":
                return obj, i + 1
            if s.startswith(QUOTE, i):
                j = s.find(QUOTE, i + len(QUOTE))
                key = s[i + len(QUOTE) : j]
                i = j + len(QUOTE)
            else:
                j = s.index(":", i)
                key = s[i:j].strip()
                i = j
            i = s.index(":", i) + 1
            val, i = _parse_value(s, i)
            obj[key] = val
    if i < len(s) and s[i] == "[":
        arr: list[Any] = []
        i += 1
        while True:
            while i < len(s) and s[i] in " \t\n\r,":
                i += 1
            if i >= len(s):
                raise ValueError("unterminated array")
            if s[i] == "]":
                return arr, i + 1
            val, i = _parse_value(s, i)
            arr.append(val)
    j = i
    while j < len(s) and s[j] not in ",}]":
        j += 1
    tok = s[i:j].strip()
    if tok == "true":
        return True, j
    if tok == "false":
        return False, j
    if tok in ("null", "None"):
        return None, j
    try:
        return int(tok), j
    except ValueError:
        pass
    try:
        return float(tok), j
    except ValueError:
        return tok, j


def render_tool_response(name: str, content: str) -> str:
    """Byte-exact equivalent of the chat template's format_tool_response_block
    for string content — used to append tool results directly to the raw
    cached token stream (continuation path) without re-rendering history."""
    return f"<|tool_response>response:{name}{{value:{QUOTE}{content}{QUOTE}}}<tool_response|>"


def parse_tool_call_body(body: str) -> dict[str, Any]:
    """'call:get_weather{city:<|"|>Paris<|"|>}' -> tool_use dict."""
    body = body.strip()
    if body.startswith("call:"):
        body = body[len("call:") :]
    brace = body.find("{")
    if brace == -1:
        name, args = body.strip(), {}
    else:
        name = body[:brace].strip()
        args, _ = _parse_value(body, brace)
        if not isinstance(args, dict):
            raise ValueError("tool call arguments must be an object")
    if not name:
        raise ValueError("empty tool name")
    return {"id": new_tool_use_id(), "name": name, "input": args}


# --------------------------------------------------------------------------
# Incremental output parser
# --------------------------------------------------------------------------

def _safe_len(buf: str, markers: tuple[str, ...]) -> int:
    """Length of the prefix that cannot be part of a marker starting at the tail."""
    n = len(buf)
    best = n
    for m in markers:
        for k in range(min(len(m), n), 0, -1):
            if m.startswith(buf[n - k :]):
                best = min(best, n - k)
                break
    return best


class StreamParser:
    """Splits incremental model output into text / thinking deltas and tool calls.

    Marker vocabulary and tool-body syntax come from the dialect. feed()
    returns events safe to emit now; flush() drains the remainder after
    generation ends. Completed tool calls also accumulate in .tool_calls.
    """

    def __init__(self, dialect=None, schemas: Schemas | None = None, thinking: bool = False) -> None:
        self.dialect = dialect or GemmaDialect()
        self.schemas = schemas
        self.buffer = ""
        # text | think_header (gemma channel-name line) | think | tool_call
        self.state = self.dialect.initial_state(thinking)
        self.tool_calls: list[dict[str, Any]] = []
        self._text_markers = tuple(self.dialect.text_markers)
        self._skip_newlines = False  # swallow newlines after a think close

    def _tool_event(self, body: str) -> list[Event]:
        try:
            call = self.dialect.parse_tool_body(body, self.schemas)
        except (ValueError, IndexError):
            # Malformed call: surface it as visible text rather than dropping it.
            return [("text", self.dialect.wrap_failed_call(body))]
        self.tool_calls.append(call)
        return [("tool_use", call)]

    def feed(self, chunk: str) -> list[Event]:
        self.buffer += chunk
        out: list[Event] = []
        while True:
            buf = self.buffer
            if self.state == "text":
                if self._skip_newlines:
                    stripped = buf.lstrip("\n")
                    if not stripped:
                        self.buffer = ""
                        return out  # wait: chunk was only newlines
                    self._skip_newlines = False
                    self.buffer = buf = stripped
                hits = [(buf.find(m), m) for m in self._text_markers]
                hits = [(i, m) for i, m in hits if i != -1]
                if hits:
                    idx, marker = min(hits)
                    if buf[:idx]:
                        out.append(("text", buf[:idx]))
                    self.buffer = buf[idx + len(marker) :]
                    self.state = self.dialect.text_markers[marker]
                    continue
                safe = _safe_len(buf, self._text_markers)
                if buf[:safe]:
                    out.append(("text", buf[:safe]))
                self.buffer = buf[safe:]
                return out
            if self.state == "think_header":
                nl = buf.find("\n")
                if nl == -1:
                    return out  # wait for the channel name line
                self.buffer = buf[nl + 1 :]
                self.state = "think"
                continue
            if self.state == "think":
                close = self.dialect.think_close
                idx = buf.find(close)
                if idx != -1:
                    if buf[:idx]:
                        out.append(("thinking", buf[:idx]))
                    self.buffer = buf[idx + len(close) :]
                    self.state = "text"
                    self._skip_newlines = True
                    continue
                safe = _safe_len(buf, (close,))
                if buf[:safe]:
                    out.append(("thinking", buf[:safe]))
                self.buffer = buf[safe:]
                return out
            # tool_call
            close = self.dialect.tool_close
            idx = buf.find(close)
            if idx == -1:
                # Buffer until the close marker. A tool body can be large (e.g. a
                # Write of a whole file), so this yields no events for a while —
                # the server's wall-clock keep-alive ping covers that silence.
                return out
            out.extend(self._tool_event(buf[:idx]))
            self.buffer = buf[idx + len(close) :]
            self.state = "text"

    def flush(self) -> list[Event]:
        buf, self.buffer = self.buffer, ""
        state, self.state = self.state, "text"
        if not buf.strip():
            return []
        if state == "think":
            return [("thinking", buf)]
        if state == "tool_call":
            # Unterminated call (e.g. hit max_tokens): try to parse anyway.
            return self._tool_event(buf)
        return [("text", buf)]
