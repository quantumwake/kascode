"""The generate -> normalized-events use case.

Turns engine GenChunks into transport-agnostic events that the HTTP adapters
(SSE / non-streaming) render into the Anthropic Messages API wire format:

    {"kind": "text" | "thinking", "text": ...}
    {"kind": "tool_use", "id": ..., "name": ..., "input": ...}
    {"kind": "ping", ...}
    {"kind": "done", "stop_reason": ..., "input_tokens": ..., "output_tokens": ...}

It owns the wall-clock keep-alive (a long tool-call body buffers server-side,
so the stream can go silent for minutes — a ping keeps it flowing) and writes
the per-thread continuation memo for the next turn.
"""

import logging
import time
from collections.abc import Iterator
from typing import Any

from ..config import DEFAULT_MAX_TOKENS
from ..prompting import StreamParser, to_chat_messages, tools_payload
from ..schema import MessagesRequest
from .continuation import req_key, try_continuation
from .ports import EngineLike

log = logging.getLogger("kas")

KEEPALIVE_SECS = 5.0


def run(
    req: MessagesRequest,
    engine: EngineLike,
    memos: dict[str, dict],
    thread: str = "main",
    persist_dir: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Generate and yield normalized events (see module docstring)."""
    assert engine is not None
    key = req_key(req)
    prompt_tokens = try_continuation(req, key, thread, engine, memos)
    if prompt_tokens is not None:
        log.info("continuation: appending tool results to raw cache (no re-render)")
    else:
        chat = to_chat_messages(req.messages, req.system, req.tool_choice, dialect=engine.dialect)
        prompt_tokens = engine.tokenize(
            chat, tools=tools_payload(req.tools), enable_thinking=req.thinking_enabled
        )
    schemas = {
        t.name: {
            k: v.get("type", "string") for k, v in (t.input_schema.get("properties") or {}).items()
        }
        for t in req.tools
    }
    parser = StreamParser(engine.dialect, schemas=schemas, thinking=req.thinking_enabled)
    stop_reason = "end_turn"
    usage = {"input_tokens": len(prompt_tokens), "output_tokens": 0}
    blocks: list[dict[str, Any]] = []  # assembled response, for the continuation memo

    def to_events(parsed) -> Iterator[dict[str, Any]]:
        for kind, payload in parsed:
            if kind == "tool_use":
                blocks.append({"type": "tool_use", **payload})
                yield {"kind": "tool_use", **payload}
            else:
                field = "text" if kind == "text" else "thinking"
                if blocks and blocks[-1]["type"] == kind:
                    blocks[-1][field] += payload
                else:
                    blocks.append({"type": kind, field: payload})
                yield {"kind": kind, "text": payload}

    # Wall-clock keep-alive. The engine emits chunk.ping only when its worker
    # queue is empty (a silent prefill). During a long tool call the queue is
    # NOT empty — it's full of token chunks the parser buffers until the
    # tool_use block closes — so to_events() yields nothing and the stream goes
    # silent for the whole tool body. The client's httpx read timeout is
    # per-gap, so that silence trips ReadTimeout even though tokens are flowing.
    # Emit a ping whenever no event has been sent for KEEPALIVE_SECS.
    last_emit = time.monotonic()

    def ping_event() -> dict[str, Any]:
        # Carry live generation detail so a quiet stream is still informative:
        # phase, tokens produced, tok/s, elapsed; lets the client render a real
        # progress line instead of a bare heartbeat.
        s = engine.stats if engine else {}
        return {
            "kind": "ping",
            "phase": s.get("phase"),
            "generated": s.get("generated"),
            "tps": s.get("tps"),
            "elapsed": s.get("elapsed"),
            "buffering": parser.state == "tool_call",
        }

    def keepalive_wrap(events) -> Iterator[dict[str, Any]]:
        nonlocal last_emit
        emitted = False
        for ev in events:
            emitted = True
            last_emit = time.monotonic()
            yield ev
        if not emitted and time.monotonic() - last_emit >= KEEPALIVE_SECS:
            last_emit = time.monotonic()
            yield ping_event()

    for chunk in engine.generate(
        prompt_tokens,
        max_tokens=req.max_tokens or DEFAULT_MAX_TOKENS,
        temperature=req.temperature,
        top_p=req.top_p,
        stop_sequences=req.stop_sequences,
        cache_key=thread,
        persist_dir=persist_dir,
    ):
        if chunk.ping:
            last_emit = time.monotonic()
            yield ping_event()
            continue
        if chunk.done:
            usage["input_tokens"] = chunk.prompt_tokens or usage["input_tokens"]
            usage["output_tokens"] = chunk.generation_tokens
            if chunk.finish_reason == "length":
                stop_reason = "max_tokens"
            elif chunk.finish_reason == "stop_sequence":
                stop_reason = "stop_sequence"
            log.info(
                "in=%d tok (cache hit %d, prefilled %d @ %.0f tok/s) | "
                "out=%d tok @ %.1f tok/s | peak %.1f GB | %s",
                chunk.prompt_tokens,
                chunk.cached_tokens,
                chunk.prompt_tokens - chunk.cached_tokens,
                chunk.prompt_tps,
                chunk.generation_tokens,
                chunk.generation_tps,
                chunk.peak_memory,
                chunk.finish_reason,
            )
            break
        yield from keepalive_wrap(to_events(parser.feed(chunk.text)))

    yield from to_events(parser.flush())

    if parser.tool_calls and stop_reason == "end_turn":
        stop_reason = "tool_use"

    memos[thread] = {
        "key": key,
        "messages": [m.model_dump() for m in req.messages],
        "blocks": blocks,
        "id2name": {c["id"]: c["name"] for c in parser.tool_calls},
        "finish": "stop" if stop_reason in ("end_turn", "tool_use") else "other",
    }
    if persist_dir:
        # Persist the continuation memo alongside the KV deltas so a resumed
        # turn can actually hit the restored cache (raw-stream continuation),
        # not just hold it. Best-effort.
        try:
            from . import kvpersist

            kvpersist.write_json(
                kvpersist.memo_path(kvpersist.thread_dir(persist_dir, thread)), memos[thread]
            )
        except Exception:
            pass
    yield {"kind": "done", "stop_reason": stop_reason, **usage}
