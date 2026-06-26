"""Streaming /v1/messages: render the event stream as Anthropic SSE frames."""

import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

from ...core.pipeline import run
from ...core.ports import EngineLike
from ...schema import MessagesRequest

log = logging.getLogger("kas")


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream(
    req: MessagesRequest,
    engine: EngineLike,
    memos: dict[str, dict],
    thread: str = "main",
    persist_dir: str | None = None,
    viz: bool = False,
) -> Iterator[str]:
    msg_id = "msg_" + uuid.uuid4().hex[:24]
    index = 0
    block_open: str | None = None  # None | "text" | "thinking"

    yield sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": req.model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )

    def close_block() -> Iterator[str]:
        nonlocal block_open, index
        if block_open is not None:
            yield sse("content_block_stop", {"type": "content_block_stop", "index": index})
            block_open = None
            index += 1

    stop_reason, usage = "end_turn", {"input_tokens": 0, "output_tokens": 0}
    for ev in run(req, engine, memos, thread, persist_dir, viz):
        if ev["kind"] == "ping":
            # Anthropic's ping event is normally bare; we attach live progress
            # under "_stats" (ignored by the SDK, read by our TUI status line).
            detail = {
                k: ev[k]
                for k in ("phase", "generated", "tps", "elapsed", "buffering")
                if ev.get(k) is not None
            }
            yield sse("ping", {"type": "ping", **({"_stats": detail} if detail else {})})
        elif ev["kind"] in ("text", "thinking"):
            if block_open != ev["kind"]:
                yield from close_block()
                start_block = (
                    {"type": "text", "text": ""}
                    if ev["kind"] == "text"
                    else {"type": "thinking", "thinking": "", "signature": ""}
                )
                yield sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": start_block,
                    },
                )
                block_open = ev["kind"]
            delta = (
                {"type": "text_delta", "text": ev["text"]}
                if ev["kind"] == "text"
                else {"type": "thinking_delta", "thinking": ev["text"]}
            )
            if ev.get("viz") is not None:  # /viz: per-token logprobs (SDK keeps model_extra)
                delta["_viz"] = ev["viz"]
            yield sse(
                "content_block_delta",
                {"type": "content_block_delta", "index": index, "delta": delta},
            )
        elif ev["kind"] == "tool_use":
            yield from close_block()
            yield sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {
                        "type": "tool_use",
                        "id": ev["id"],
                        "name": ev["name"],
                        "input": {},
                    },
                },
            )
            yield sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(ev["input"], ensure_ascii=False),
                    },
                },
            )
            yield sse("content_block_stop", {"type": "content_block_stop", "index": index})
            index += 1
        else:
            stop_reason = ev["stop_reason"]
            usage = {"input_tokens": ev["input_tokens"], "output_tokens": ev["output_tokens"]}

    yield from close_block()
    yield sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": usage,
        },
    )
    yield sse("message_stop", {"type": "message_stop"})


def stream_safe(
    req: MessagesRequest,
    engine: EngineLike,
    memos: dict[str, dict],
    thread: str = "main",
    persist_dir: str | None = None,
    viz: bool = False,
) -> Iterator[str]:
    """Wrap stream so server-side failures become an SSE error event the SDK
    can raise cleanly, instead of an aborted chunked response
    (httpx: 'peer closed connection without sending complete message body')."""
    try:
        yield from stream(req, engine, memos, thread, persist_dir, viz)
    except Exception as exc:
        log.exception("error during streaming generation")
        yield sse(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": f"{type(exc).__name__}: {exc}"},
            },
        )
