"""Unit tests for Gemma-4 native output parsing and message rendering.

Run:  uv run python tests/test_parser.py
"""

import sys

sys.path.insert(0, ".")

from server.prompting import StreamParser, parse_tool_call_body, to_chat_messages
from server.schema import Message

CANNED = (
    "<|channel>thought\nUser wants weather. Call the tool.\n<channel|>"
    "Let me check.\n\n"
    '<|tool_call>call:get_weather{city:<|"|>Paris<|"|>,units:<|"|>metric<|"|>}<tool_call|>'
)


def collect(parser: StreamParser, chunks):
    events = []
    for c in chunks:
        events.extend(parser.feed(c))
    events.extend(parser.flush())
    return events


def merged(events, kind):
    return "".join(p for k, p in events if k == kind)


# 1. full canned response in awkward 5-char chunks
p = StreamParser()
events = collect(p, [CANNED[i : i + 5] for i in range(0, len(CANNED), 5)])
assert merged(events, "thinking") == "User wants weather. Call the tool.\n", repr(
    merged(events, "thinking")
)
assert merged(events, "text") == "Let me check.\n\n"
assert p.tool_calls[0]["name"] == "get_weather"
assert p.tool_calls[0]["input"] == {"city": "Paris", "units": "metric"}, p.tool_calls

# 2. argument syntax: nested objects, arrays, numbers, booleans
call = parse_tool_call_body(
    'call:run{cmd:<|"|>ls -la<|"|>,count:3,ratio:0.5,'
    'deep:{<|"|>k<|"|>:[1,true,<|"|>x<|"|>]},flag:false}'
)
assert call["input"] == {
    "cmd": "ls -la",
    "count": 3,
    "ratio": 0.5,
    "deep": {"k": [1, True, "x"]},
    "flag": False,
}, call["input"]

# 3. empty args + no-brace call
assert parse_tool_call_body("call:list_dir{}")["input"] == {}
assert parse_tool_call_body("call:list_dir")["input"] == {}

# 4. plain text with angle brackets passes through (holdback releases on flush)
p = StreamParser()
events = collect(p, ["if a <", " b: print(1) # <|not_a_marker", " done"])
assert merged(events, "text") == "if a < b: print(1) # <|not_a_marker done", repr(
    merged(events, "text")
)

# 5. malformed tool call surfaces as text, not dropped
p = StreamParser()
events = collect(p, ["<|tool_call>garbage with { no close<tool_call|> after"])
assert p.tool_calls == []
assert "garbage" in merged(events, "text")

# 6. unterminated tool call at max_tokens still parses
p = StreamParser()
events = collect(p, ['<|tool_call>call:read_file{path:<|"|>a.py<|"|>}'])
assert p.tool_calls and p.tool_calls[0]["name"] == "read_file"

# 7. message rendering: tool results -> role:"tool", thinking -> reasoning
msgs = [
    Message(role="user", content="check the weather"),
    Message(
        role="assistant",
        content=[
            {"type": "thinking", "thinking": "need the tool", "signature": ""},
            {"type": "text", "text": "Checking."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "get_weather",
                "input": {"city": "Paris"},
            },
        ],
    ),
    Message(
        role="user",
        content=[
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "18C rain"},
            {"type": "text", "text": "thanks, and tomorrow?"},
        ],
    ),
]
chat = to_chat_messages(msgs, "be brief", None)
assert [m["role"] for m in chat] == ["system", "user", "assistant", "tool", "user"], chat
assert chat[2]["tool_calls"][0]["function"]["name"] == "get_weather"
assert chat[2]["reasoning"] == "need the tool"
assert chat[3]["tool_call_id"] == "toolu_1" and chat[3]["content"] == "18C rain"

print("all parser/prompting tests passed")


# ---------------- Qwen dialect ----------------
from server.prompting import QwenDialect, detect_dialect

QWEN_CANNED = (
    "I should check the weather for the user.\n</think>\n\n"
    "Let me check.\n\n"
    "<tool_call>\n<function=get_weather>\n<parameter=city>\nParis\n</parameter>\n"
    "<parameter=retries>\n3\n</parameter>\n</function>\n</tool_call>"
)
SCHEMAS = {"get_weather": {"city": "string", "retries": "integer"}}

# 8. thinking pre-opened by the generation prompt; awkward chunking
p = StreamParser(QwenDialect(), schemas=SCHEMAS, thinking=True)
events = collect(p, [QWEN_CANNED[i : i + 7] for i in range(0, len(QWEN_CANNED), 7)])
assert merged(events, "thinking") == "I should check the weather for the user.\n", repr(
    merged(events, "thinking")
)
assert merged(events, "text") == "Let me check.\n\n"
assert p.tool_calls[0]["name"] == "get_weather"
assert p.tool_calls[0]["input"] == {"city": "Paris", "retries": 3}, p.tool_calls

# 9. thinking disabled -> starts in text; explicit <think> still recognized
p = StreamParser(QwenDialect(), thinking=False)
events = collect(p, ["plain answer <think>\nhmm\n</think>\n\nmore text"])
assert merged(events, "text") == "plain answer more text", repr(merged(events, "text"))
assert merged(events, "thinking") == "\nhmm\n", repr(merged(events, "thinking"))

# 10. multi-line string parameter survives verbatim; schema coercion of bool/array
p = StreamParser(
    QwenDialect(),
    schemas={"write_file": {"content": "string", "append": "boolean", "tags": "array"}},
    thinking=False,
)
body = (
    "<tool_call>\n<function=write_file>\n"
    "<parameter=content>\nline one\nline two\n</parameter>\n"
    "<parameter=append>\ntrue\n</parameter>\n"
    '<parameter=tags>\n["a", "b"]\n</parameter>\n</function>\n</tool_call>'
)
events = collect(p, [body])
call = p.tool_calls[0]
assert call["input"] == {"content": "line one\nline two", "append": True, "tags": ["a", "b"]}, call[
    "input"
]

# 11. malformed qwen call surfaces as text
p = StreamParser(QwenDialect(), thinking=False)
events = collect(p, ["<tool_call>\nno function tag here\n</tool_call> after"])
assert p.tool_calls == [] and "no function tag" in merged(events, "text")

# 12. dialect detection
assert detect_dialect("...<|tool_call>call:...").name == "gemma"
assert detect_dialect("{{ '<|im_start|>' }} <function=...").name == "qwen-xml"
assert detect_dialect(None).name == "gemma"

# 13. qwen assistant entry embeds thinking in content
chat = to_chat_messages(
    [
        Message(
            role="assistant",
            content=[
                {"type": "thinking", "thinking": "plan", "signature": ""},
                {"type": "text", "text": "Done."},
            ],
        )
    ],
    None,
    None,
    dialect=QwenDialect(),
)
assert chat[0]["content"] == "<think>\nplan\n</think>\n\nDone.", chat

print("qwen dialect tests passed")

# 14. gemma-4 declares the scaffolding stop-strings it emits so they don't leak
#     into the visible answer (<turn|> closes a turn, <|tool_response> is its
#     await-result signal after a tool call). The engine merges these into its
#     stop set; this guards against them being dropped from the dialect.
from server.prompting.dialects import GemmaDialect

assert "<turn|>" in GemmaDialect.stop_strings, GemmaDialect.stop_strings
assert "<|tool_response>" in GemmaDialect.stop_strings, GemmaDialect.stop_strings

print("gemma stop-string tests passed")
