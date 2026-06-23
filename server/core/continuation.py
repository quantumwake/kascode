"""Continuation memo: append a new turn's wire bytes directly to a thread's
raw cached token stream, skipping a full re-render.

Gemma's RotatingKVCache (sliding window) and Qwen3.5/3.6's ArraysCache
(linear-attention state) can't be trimmed, so any divergence between the
cached raw stream and a re-rendered transcript forces a full re-prefill. The
agent loop's requests are always "previous messages + assistant echo + tool
results", so when we recognize that exact shape we append the tool responses
(in template wire format) directly to the cached stream: pure append, no trim,
full cache hit at any length.

Pure functions — they take the engine (for cache snapshot + encode + dialect)
and the per-thread memo store explicitly, so they carry no module state and
are unit-testable without a model.
"""

import json
from typing import Any

from ..prompting import _tool_result_text
from ..schema import MessagesRequest, ToolResultBlock
from .ports import EngineLike


def req_key(req: MessagesRequest) -> str:
    return json.dumps(
        {
            "system": req.system,
            "tools": [t.model_dump() for t in req.tools],
            "thinking": req.thinking_enabled,
            "tool_choice": req.tool_choice,
        },
        sort_keys=True,
    )


def norm_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


def echo_matches(echo_content: Any, blocks: list[dict[str, Any]]) -> bool:
    """Does the client's echoed assistant turn match what we generated?"""
    echo = norm_blocks(echo_content)
    if len(echo) != len(blocks):
        return False
    for e, b in zip(echo, blocks, strict=False):
        if e.get("type") != b["type"]:
            return False
        if b["type"] == "text" and e.get("text", "").strip() != b["text"].strip():
            return False
        if b["type"] == "thinking" and e.get("thinking", "").strip() != b["thinking"].strip():
            return False
        if b["type"] == "tool_use" and (
            e.get("id") != b["id"] or e.get("name") != b["name"] or e.get("input") != b["input"]
        ):
            return False
    return True


def try_continuation(
    req: MessagesRequest, key: str, thread: str, engine: EngineLike, memos: dict[str, dict]
) -> list[int] | None:
    """Return prompt tokens built as raw-cache + new-turn wire bytes, or None.

    Handles the trailing user message shapes the agent produces:
      - pure tool results                       (tool loop)
      - tool results + text                     (steering injection)
      - pure text                               (next REPL/TUI message)
    Wire-format notes: generation stops on <eos>/<turn|>/<|tool_response> and
    the final stop token is withheld from the cache, so after tool calls the
    tail starts directly at <|tool_response>, while a user-text turn must
    supply the <turn|> closure itself.
    """
    if not engine.dialect.supports_continuation:
        return None  # trimmable-cache dialects get prefix reuse in the engine
    memo = memos.get(thread)
    if memo is None or memo["key"] != key or memo["finish"] != "stop":
        return None
    msgs = [m.model_dump() for m in req.messages]
    prev = memo["messages"]
    if len(msgs) != len(prev) + 2 or msgs[: len(prev)] != prev:
        return None
    echo, last = msgs[-2], msgs[-1]
    if echo["role"] != "assistant" or last["role"] != "user":
        return None
    if not echo_matches(echo["content"], memo["blocks"]):
        return None

    blocks = (
        [{"type": "text", "text": last["content"]}]
        if isinstance(last["content"], str)
        else last["content"]
    )
    results = [b for b in blocks if b.get("type") == "tool_result"]
    texts = [b for b in blocks if b.get("type") == "text"]
    # only the agent shapes; tool results must precede text (no interleaving)
    if len(results) + len(texts) != len(blocks) or not blocks:
        return None
    if blocks[: len(results)] != results:
        return None

    result_pairs = []
    for b in results:
        name = memo["id2name"].get(b["tool_use_id"])
        if name is None:
            return None
        result_pairs.append((name, _tool_result_text(ToolResultBlock(**b))))
    tail = engine.dialect.continuation_tail(
        result_pairs, [t.get("text", "") for t in texts], req.thinking_enabled
    )
    if tail is None:
        return None
    cached = engine.cache_snapshot(thread)
    if not cached:
        return None
    return cached + engine.encode(tail)
