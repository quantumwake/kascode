"""Standard re-render dialects for the main open model families.

Unlike Gemma/Qwen3.x (which use the append-only continuation memo because their
caches can't be trimmed — see continuation.py), these set
``supports_continuation = False``: the server re-renders the full transcript
through the model's own chat template every turn and relies on trimmable-cache
prefix reuse. That keeps each dialect tiny — it only has to describe how tool
calls appear in the OUTPUT stream (the opener/closer markers + how to parse the
body); history rendering is the template's job.

Families covered:
  - HermesDialect   ChatML JSON tool calls: <tool_call>{"name":..,"arguments":..}</tool_call>
                    (Qwen2.5-Instruct, Qwen3-Next, Nous-Hermes, and most ChatML fine-tunes)
  - LlamaDialect    Llama 3.x: <|python_tag|>{"name":..,"parameters":..} ... <|eom_id|>
  - MistralDialect  Mistral/Mixtral: [TOOL_CALLS][{"name":..,"arguments":..}]
  - DeepSeekDialect DeepSeek-V3/R1: <｜tool▁calls▁begin｜>…function<｜tool▁sep｜>name```json{…}```…
"""

import json
import re
from typing import Any

from .wire import Schemas, new_tool_use_id


class _StandardDialect:
    """Base for re-render dialects. Subclasses set name + the output-stream
    tool-call markers and parse_tool_body; everything else is shared.
    """

    supports_continuation = False
    template_kwargs: dict = {}
    # Reasoning models in these families all use <think>...</think>; including the
    # marker is harmless for non-reasoning models (it simply never fires).
    text_markers = {"<think>": "think", "<tool_call>": "tool_call"}
    think_close = "</think>"
    tool_close = "</tool_call>"
    tool_open = "<tool_call>"
    fail_close = None  # defaults to tool_close in wrap_failed_call

    def initial_state(self, thinking_enabled: bool) -> str:
        # These templates do NOT pre-open a <think> block in the generation
        # prompt, so the model emits its own opener — always start in text.
        return "text"

    def continuation_tail(
        self, results: list[tuple[str, str]], texts: list[str], thinking: bool
    ) -> str | None:
        return None  # never called (supports_continuation is False)

    def assistant_entry(
        self, texts: list[str], reasoning: list[str], tool_calls: list[dict]
    ) -> dict:
        # OpenAI-shaped assistant turn consumed by apply_chat_template. Prior
        # reasoning is dropped: every one of these templates strips <think>
        # content from history, so re-emitting it would diverge from training.
        entry: dict[str, Any] = {"role": "assistant", "content": "\n\n".join(texts)}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        return entry

    def wrap_failed_call(self, body: str) -> str:
        close = self.tool_close if self.fail_close is None else self.fail_close
        return f"{self.tool_open}{body}{close}"

    def parse_tool_body(self, body: str, schemas: Schemas | None) -> dict:
        raise NotImplementedError


def _call(name: str, args: Any) -> dict:
    """Build a tool_use from a parsed name + arguments (dict or JSON string)."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return {"id": new_tool_use_id(), "name": name, "input": args}


def _first_json_object(text: str) -> dict:
    """Parse the first top-level JSON object in `text` (tolerates surrounding
    prose / trailing tokens that some models append after the call)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in tool call")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unterminated JSON object in tool call")


class _JsonDialect(_StandardDialect):
    """Base for the JSON-bodied families (Hermes / Llama / Mistral). They differ
    ONLY in their stream markers (data) — the tool-call body is the same shape in
    all three: a JSON object, or a JSON array whose first element is the call
    (Mistral). Name from "name"; args from "arguments" or its "parameters" alias.
    So the parse lives here once and subclasses carry only marker data."""

    def parse_tool_body(self, body: str, schemas: Schemas | None) -> dict:
        body = body.strip()
        try:
            data = json.loads(body)  # clean object or array
        except json.JSONDecodeError:
            data = _first_json_object(body)  # tolerate prose / trailing tokens
        # Mistral wraps calls in an array; the agent loop issues one at a time, so
        # surface the first. (Parallel calls aren't expressible in the single-call
        # parser interface.) Objects pass straight through.
        call = data[0] if isinstance(data, list) else data
        name = call.get("name")
        if not name:
            raise ValueError("no name in tool call")
        return _call(name, call.get("arguments", call.get("parameters", {})))


class HermesDialect(_JsonDialect):
    """ChatML JSON tool calls — the most common interchange format.

    <tool_call>{"name": "read_file", "arguments": {"path": "x.py"}}</tool_call>
    """

    name = "hermes-json"


class LlamaDialect(_JsonDialect):
    """Llama 3.x: a bare JSON object, optionally fenced by <|python_tag|> …
    <|eom_id|>. (Llama writes "parameters"; the shared parser accepts it.)"""

    name = "llama-json"
    text_markers = {"<think>": "think", "<|python_tag|>": "tool_call"}
    tool_open = "<|python_tag|>"
    tool_close = "<|eom_id|>"  # EOS-class: usually withheld, so flush() parses
    fail_close = ""


class MistralDialect(_JsonDialect):
    """Mistral/Mixtral: [TOOL_CALLS] then a JSON array. There is no closing
    marker — the array runs to end-of-message — so the close is the (withheld)
    EOS and flush() parses the buffered body."""

    name = "mistral"
    text_markers = {"<think>": "think", "[TOOL_CALLS]": "tool_call"}
    tool_open = "[TOOL_CALLS]"
    tool_close = "</s>"  # withheld EOS -> never seen in stream -> flush() parses
    fail_close = ""


# DeepSeek special tokens use fullwidth bar (U+FF5C) + lower-block (U+2581).
_DS_CALLS_BEGIN = "<｜tool▁calls▁begin｜>"
_DS_CALLS_END = "<｜tool▁calls▁end｜>"
_DS_SEP = "<｜tool▁sep｜>"


class DeepSeekDialect(_StandardDialect):
    """DeepSeek-V3/R1:

    <｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>NAME
    ```json
    {ARGS}
    ```<｜tool▁call▁end｜><｜tool▁calls▁end｜>
    """

    name = "deepseek"
    text_markers = {"<think>": "think", _DS_CALLS_BEGIN: "tool_call"}
    tool_open = _DS_CALLS_BEGIN
    tool_close = _DS_CALLS_END
    fail_close = _DS_CALLS_END

    def parse_tool_body(self, body: str, schemas: Schemas | None) -> dict:
        m = re.search(re.escape(_DS_SEP) + r"\s*([^\n`]+)", body)
        if m is None:
            raise ValueError("no <｜tool▁sep｜>name in tool call")
        name = m.group(1).strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
        args = fence.group(1) if fence else "{}"
        return _call(name, args)


class KimiDialect(_StandardDialect):
    """Moonshot Kimi-K2 — its own section/marker scheme (NOT ChatML/Hermes):

        <|tool_calls_section_begin|>
        <|tool_call_begin|>functions.NAME:0<|tool_call_argument_begin|>{ARGS}<|tool_call_end|>
        <|tool_calls_section_end|>

    We open/close on the SECTION so the inner per-call markers never leak as
    text, and parse the first call from the body.
    """

    name = "kimi-k2"
    text_markers = {"<think>": "think", "<|tool_calls_section_begin|>": "tool_call"}
    tool_open = "<|tool_calls_section_begin|>"
    tool_close = "<|tool_calls_section_end|>"
    fail_close = "<|tool_calls_section_end|>"

    def parse_tool_body(self, body: str, schemas: Schemas | None) -> dict:
        m = re.search(r"functions\.([^:\s]+)\s*:\s*\d+", body)
        if m is None:
            raise ValueError("no functions.name:idx in tool call")
        name = m.group(1).strip()
        a = re.search(r"<\|tool_call_argument_begin\|>(.*?)(?:<\|tool_call_end\|>|$)", body, re.S)
        args = a.group(1) if a else "{}"
        return _call(name, _first_json_object(args) if "{" in args else {})


class HarmonyDialect(_StandardDialect):
    """OpenAI gpt-oss "harmony" channel format. The model emits a sequence of
    channel messages; the channel selects the meaning:

        <|channel|>analysis<|message|>...reasoning...<|end|>
        <|channel|>final<|message|>...answer...<|return|>
        <|channel|>commentary to=functions.NAME <|constrain|>json<|message|>{args}<|call|>

    We map analysis->thinking, final/commentary-preamble->text, and the
    commentary-to-functions form->tool_call. Role re-declarations
    (<|start|>assistant) between channels are consumed as no-op text markers so
    they don't leak. (Markers are confirmed against a live gpt-oss-20b capture.)
    """

    name = "harmony"
    text_markers = {
        "<|channel|>analysis<|message|>": "think",
        "<|channel|>commentary to=functions.": "tool_call",
        "<|channel|>final<|message|>": "text",
        "<|channel|>commentary<|message|>": "text",
        "<|start|>assistant": "text",
    }
    think_close = "<|end|>"
    tool_close = "<|call|>"  # EOS-class: may be withheld -> flush() parses
    tool_open = "<|channel|>commentary to=functions."
    fail_close = ""

    def parse_tool_body(self, body: str, schemas: Schemas | None) -> dict:
        # body starts right after "to=functions." -> "NAME <|constrain|>json<|message|>{args}"
        m = re.match(r"\s*([\w.\-]+)", body)
        if m is None:
            raise ValueError("no function name in harmony tool call")
        name = m.group(1)
        a = re.search(r"<\|message\|>(.*)", body, re.S)
        args = a.group(1) if a else "{}"
        return _call(name, _first_json_object(args) if "{" in args else {})
