"""Characterization tests for the raw-stream continuation path.

These lock the behaviour of the continuation memo BEFORE the hexagonal
refactor moves it out of server/app.py: _echo_matches, the per-dialect
continuation_tail wire bytes, and _try_continuation's end-to-end assembly
(cached tokens + encoded new-turn tail). No model weights needed.

Run:  uv run python tests/test_continuation.py
"""

import sys

sys.path.insert(0, ".")

import server.app as app_module
from server.app import _echo_matches, _norm_blocks, _req_key, _try_continuation
from server.prompting import GemmaDialect, QwenDialect
from server.schema import MessagesRequest


class FakeEngine:
    """Stands in for the MLX engine: records the tail it was asked to encode
    and returns the cached token snapshot, so we can assert both the wire
    bytes and the final prompt-token assembly."""

    def __init__(self, dialect, cached):
        self.dialect = dialect
        self._cached = cached
        self.encoded_text = None

    def cache_snapshot(self, thread="main"):
        return list(self._cached)

    def encode(self, text):
        self.encoded_text = text
        return [9001, 9002]  # sentinel "encoded tail" tokens


def req(messages, tools=None, system="sys", thinking=False):
    return MessagesRequest(
        model="fake",
        max_tokens=256,
        system=system,
        tools=tools or [],
        thinking={"type": "enabled"} if thinking else None,
        messages=messages,
    )


# ---------------------------------------------------------------------------
# _norm_blocks / _echo_matches
# ---------------------------------------------------------------------------

assert _norm_blocks("hi") == [{"type": "text", "text": "hi"}]
blocks = [{"type": "text", "text": "Let me check."}, {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Paris"}}]

# Exact match (whitespace tolerant on text/thinking).
assert _echo_matches(
    [{"type": "text", "text": "  Let me check.  "}, {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Paris"}}],
    blocks,
)
# Tool input divergence -> no match.
assert not _echo_matches(
    [{"type": "text", "text": "Let me check."}, {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "London"}}],
    blocks,
)
# Block count divergence -> no match.
assert not _echo_matches([{"type": "text", "text": "Let me check."}], blocks)
print("_norm_blocks / _echo_matches: OK")


# ---------------------------------------------------------------------------
# continuation_tail wire bytes (golden) — Gemma
# ---------------------------------------------------------------------------

g = GemmaDialect()
# tool results only: starts directly at <|tool_response>, no turn closure.
tail = g.continuation_tail([("get_weather", "18C rain")], [], thinking=False)
assert tail == '<|tool_response>response:get_weather{value:<|"|>18C rain<|"|>}<tool_response|>', repr(tail)
# pure text turn (no results): supplies <turn|> closure, opens a thought when not thinking.
tail = g.continuation_tail([], ["next thing"], thinking=False)
assert tail == "<turn|>\n<|turn>user\nnext thing<turn|>\n<|turn>model\n<|channel>thought\n<channel|>", repr(tail)
# text turn with thinking on: no pre-opened empty thought.
tail = g.continuation_tail([], ["next thing"], thinking=True)
assert tail == "<turn|>\n<|turn>user\nnext thing<turn|>\n<|turn>model\n", repr(tail)
# empty text -> None (caller falls back to full re-render).
assert g.continuation_tail([], ["  "], thinking=False) is None
print("gemma continuation_tail: OK")


# ---------------------------------------------------------------------------
# continuation_tail wire bytes (golden) — Qwen ChatML
# ---------------------------------------------------------------------------

q = QwenDialect()
tail = q.continuation_tail([("get_weather", "18C rain")], [], thinking=False)
assert tail == (
    "<|im_end|>\n<|im_start|>user\n<tool_response>\n18C rain\n</tool_response><|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
), repr(tail)
tail = q.continuation_tail([], ["hello"], thinking=True)
assert tail == "<|im_end|>\n<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n<think>\n", repr(tail)
print("qwen continuation_tail: OK")


# ---------------------------------------------------------------------------
# _try_continuation end-to-end: cached tokens + encoded tail
# ---------------------------------------------------------------------------

def run_case(dialect, thinking):
    cached = [1, 2, 3, 4]
    app_module.engine = FakeEngine(dialect, cached)
    app_module._memos.clear()

    prev = [{"role": "user", "content": "Weather in Paris?"}]
    first = req([dict(m) for m in prev], thinking=thinking)
    key = _req_key(first)

    echo_blocks = [
        {"type": "text", "text": "Let me check."},
        {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Paris"}},
    ]
    app_module._memos["main"] = {
        "key": key,
        "messages": [m.model_dump() for m in first.messages],
        "blocks": echo_blocks,
        "id2name": {"toolu_1": "get_weather"},
        "finish": "stop",
    }

    follow = req(
        prev
        + [
            {"role": "assistant", "content": echo_blocks},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "18C rain"}]},
        ],
        thinking=thinking,
    )
    tokens = _try_continuation(follow, key, "main")
    assert tokens == cached + [9001, 9002], tokens
    expected_tail = dialect.continuation_tail([("get_weather", "18C rain")], [], thinking)
    assert app_module.engine.encoded_text == expected_tail, app_module.engine.encoded_text


run_case(GemmaDialect(), thinking=False)
run_case(QwenDialect(), thinking=True)

# Key mismatch (e.g. tools changed mid-session) -> no continuation.
app_module.engine = FakeEngine(GemmaDialect(), [1, 2])
app_module._memos["main"]["key"] = "different-key"
follow = req([{"role": "user", "content": "Weather in Paris?"}])
assert _try_continuation(follow, _req_key(follow), "main") is None
print("_try_continuation end-to-end: OK")

print("all continuation tests passed")
