"""Model chat dialects, auto-detected from the tokenizer's chat template.

  - GemmaDialect (gemma-4): <|channel>thought / <|tool_call>call:name{...}
    with Gemma's custom argument serialization; supports raw-stream
    continuation (its rotating caches can't be trimmed, so we keep the raw
    token stream append-only).
  - QwenDialect (qwen3.x ChatML): <think>...</think> blocks (pre-opened by
    the generation prompt) and XML-ish tool calls
    <tool_call><function=name><parameter=key>value</parameter>...; arguments
    arrive as raw strings and are coerced via the tool's input_schema.

Both dialects use the raw-stream continuation memo: Gemma's rotating caches
and Qwen3.5/3.6's untrimmable ArraysCache (linear-attention state) both reset
on any divergence, so the server appends new-turn wire bytes directly to the
cached token stream instead of re-rendering history.
"""

import json
import re
from typing import Any

from .gemma_args import parse_tool_call_body
from .wire import CH_CLOSE, CH_OPEN, QUOTE, TC_CLOSE, TC_OPEN, Schemas, new_tool_use_id


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
        from .gemma_args import render_tool_response

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
