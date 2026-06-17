"""Anthropic Messages API-compatible server backed by a local MLX model.

Run:  uv run uvicorn server.app:app --port 8765

Point any official Anthropic SDK at it:

    client = anthropic.Anthropic(base_url="http://127.0.0.1:8765", api_key="local")
"""

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Iterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from .engine import Engine
from .prompting import (
    StreamParser,
    _tool_result_text,
    render_tool_response,
    to_chat_messages,
    tools_payload,
)
from .schema import MessagesRequest, ToolResultBlock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("kas")

MODEL_ID = os.environ.get("KAS_MODEL", "mlx-community/Qwen3.6-27B-4bit")
DEFAULT_MAX_TOKENS = 8192

engine: Engine | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    try:
        from scripts.banner import print_console

        print_console(model=MODEL_ID, extra="inference server")
    except Exception:
        pass
    engine = Engine(MODEL_ID)
    yield


app = FastAPI(title="kas", lifespan=lifespan)


def error_response(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "error", "error": {"type": err_type, "message": message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    return error_response(400, "invalid_request_error", str(exc.errors()[:3]))


@app.exception_handler(Exception)
async def fallback_handler(_: Request, exc: Exception):
    log.exception("internal error")
    return error_response(500, "api_error", f"{type(exc).__name__}: {exc}")


def _served_id() -> str:
    return engine.model_id if engine else MODEL_ID


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    mid = _served_id()
    return {
        "data": [
            {
                "type": "model",
                "id": mid,
                "display_name": mid,
                "dialect": getattr(engine, "dialect", None) and engine.dialect.name,
                "context_length": getattr(engine, "context_length", None),
            }
        ]
    }


@app.post("/v1/models/select")
def select_model(payload: dict[str, Any]):
    """Hot-swap the served model. Queued behind any in-flight generation."""
    model_id = (payload or {}).get("model")
    if not model_id or not isinstance(model_id, str):
        return error_response(400, "invalid_request_error", "body must include 'model'")
    if engine is None:
        return error_response(500, "api_error", "engine not ready")
    if model_id == engine.model_id:
        return {"ok": True, "model": engine.model_id, "dialect": engine.dialect.name}
    try:
        engine.swap(model_id)
    except Exception as exc:
        log.exception("model swap failed")
        return error_response(500, "api_error", f"swap failed: {type(exc).__name__}: {exc}")
    _memos.clear()  # continuation memos are model-specific
    return {"ok": True, "model": engine.model_id, "dialect": engine.dialect.name}


@app.get("/v1/stats")
def live_stats() -> dict[str, Any]:
    """Live generation progress — polled by clients while the stream is quiet
    (e.g. during a long tool call, whose body is buffered until it closes)."""
    if engine is None:
        return {"model": MODEL_ID, "active": False}
    return {"model": MODEL_ID, **engine.stats, **engine.ping_status()}


def _validate(req: MessagesRequest) -> JSONResponse | None:
    if not req.messages:
        return error_response(400, "invalid_request_error", "messages: must not be empty")
    if req.messages[0].role != "user":
        return error_response(400, "invalid_request_error", "first message must use the user role")
    if req.messages[-1].role == "assistant":
        return error_response(
            400, "invalid_request_error", "assistant-turn prefill is not supported"
        )
    return None


# --------------------------------------------------------------------------
# Continuation memo
#
# Gemma-4 puts RotatingKVCache (sliding window 512) on most layers, and a
# rotated cache cannot be trimmed — so any divergence between the cached raw
# stream and a re-rendered transcript forces a full re-prefill. The agent
# loop's requests are always "previous messages + assistant echo + tool
# results", so when we recognize that exact shape we skip re-rendering and
# append the tool responses (in template wire format) directly to the raw
# cached token stream: pure append, no trim, full cache hit at any length.
# --------------------------------------------------------------------------

# Continuation memo per conversation thread (main + each subagent).
_memos: dict[str, dict[str, Any]] = {}


def _req_key(req: MessagesRequest) -> str:
    return json.dumps(
        {
            "system": req.system,
            "tools": [t.model_dump() for t in req.tools],
            "thinking": req.thinking_enabled,
            "tool_choice": req.tool_choice,
        },
        sort_keys=True,
    )


def _norm_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


def _echo_matches(echo_content: Any, blocks: list[dict[str, Any]]) -> bool:
    """Does the client's echoed assistant turn match what we generated?"""
    echo = _norm_blocks(echo_content)
    if len(echo) != len(blocks):
        return False
    for e, b in zip(echo, blocks):
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


def _try_continuation(req: MessagesRequest, key: str, thread: str) -> list[int] | None:
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
    memo = _memos.get(thread)
    if memo is None or memo["key"] != key or memo["finish"] != "stop":
        return None
    msgs = [m.model_dump() for m in req.messages]
    prev = memo["messages"]
    if len(msgs) != len(prev) + 2 or msgs[: len(prev)] != prev:
        return None
    echo, last = msgs[-2], msgs[-1]
    if echo["role"] != "assistant" or last["role"] != "user":
        return None
    if not _echo_matches(echo["content"], memo["blocks"]):
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


def _run(req: MessagesRequest, thread: str = "main") -> Iterator[dict[str, Any]]:
    """Generate and yield normalized events:

    {"kind": "text" | "thinking", "text": ...}
    {"kind": "tool_use", "id": ..., "name": ..., "input": ...}
    {"kind": "done", "stop_reason": ..., "input_tokens": ..., "output_tokens": ...}
    """
    assert engine is not None
    key = _req_key(req)
    prompt_tokens = _try_continuation(req, key, thread)
    if prompt_tokens is not None:
        log.info("continuation: appending tool results to raw cache (no re-render)")
    else:
        chat = to_chat_messages(req.messages, req.system, req.tool_choice, dialect=engine.dialect)
        prompt_tokens = engine.tokenize(
            chat, tools=tools_payload(req.tools), enable_thinking=req.thinking_enabled
        )
    schemas = {
        t.name: {
            k: v.get("type", "string")
            for k, v in (t.input_schema.get("properties") or {}).items()
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

    # Wall-clock keep-alive. The engine only emits chunk.ping when its worker
    # queue is empty (a silent prefill). During a long tool call the queue is
    # NOT empty — it's full of token chunks the parser buffers until the
    # tool_use block closes — so to_events() yields nothing and the SSE stream
    # goes silent for the whole tool body. The client's httpx read timeout is
    # per-gap, so that silence trips ReadTimeout even though tokens are flowing.
    # Emit a ping whenever no event has been sent for KEEPALIVE_SECS, regardless
    # of why the stream is quiet.
    KEEPALIVE_SECS = 5.0
    last_emit = time.monotonic()

    def ping_event() -> dict[str, Any]:
        # Carry live generation detail so a quiet stream is still informative:
        # phase ("generate" mid tool-call buffering, "prefill" while warming up),
        # tokens produced, tok/s, and elapsed. Lets the client render a real
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
                "in=%d tok (cache hit %d, prefilled %d @ %.0f tok/s) | out=%d tok @ %.1f tok/s | peak %.1f GB | %s",
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

    _memos[thread] = {
        "key": key,
        "messages": [m.model_dump() for m in req.messages],
        "blocks": blocks,
        "id2name": {c["id"]: c["name"] for c in parser.tool_calls},
        "finish": "stop" if stop_reason in ("end_turn", "tool_use") else "other",
    }
    yield {"kind": "done", "stop_reason": stop_reason, **usage}


def _complete(req: MessagesRequest, thread: str = "main") -> JSONResponse:
    content: list[dict[str, Any]] = []
    stop_reason, usage = "end_turn", {"input_tokens": 0, "output_tokens": 0}
    for ev in _run(req, thread):
        if ev["kind"] == "ping":
            continue  # heartbeat only; nothing to aggregate
        if ev["kind"] == "text":
            if content and content[-1]["type"] == "text":
                content[-1]["text"] += ev["text"]
            else:
                content.append({"type": "text", "text": ev["text"]})
        elif ev["kind"] == "thinking":
            if content and content[-1]["type"] == "thinking":
                content[-1]["thinking"] += ev["text"]
            else:
                content.append({"type": "thinking", "thinking": ev["text"], "signature": ""})
        elif ev["kind"] == "tool_use":
            content.append(
                {"type": "tool_use", "id": ev["id"], "name": ev["name"], "input": ev["input"]}
            )
        else:
            stop_reason = ev["stop_reason"]
            usage = {"input_tokens": ev["input_tokens"], "output_tokens": ev["output_tokens"]}
    for block in content:
        if block["type"] == "text":
            block["text"] = block["text"].strip()
        elif block["type"] == "thinking":
            block["thinking"] = block["thinking"].strip()
    content = [
        b
        for b in content
        if (b["type"] == "text" and b["text"])
        or (b["type"] == "thinking" and b["thinking"])
        or b["type"] == "tool_use"
    ]
    return JSONResponse(
        {
            "id": "msg_" + uuid.uuid4().hex[:24],
            "type": "message",
            "role": "assistant",
            "model": req.model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage,
        }
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream(req: MessagesRequest, thread: str = "main") -> Iterator[str]:
    msg_id = "msg_" + uuid.uuid4().hex[:24]
    index = 0
    block_open: str | None = None  # None | "text" | "thinking"

    yield _sse(
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
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
            block_open = None
            index += 1

    stop_reason, usage = "end_turn", {"input_tokens": 0, "output_tokens": 0}
    for ev in _run(req, thread):
        if ev["kind"] == "ping":
            # Anthropic's ping event is normally bare; we attach live progress
            # under "_stats" (ignored by the SDK, read by our TUI status line).
            detail = {k: ev[k] for k in ("phase", "generated", "tps", "elapsed", "buffering")
                      if ev.get(k) is not None}
            yield _sse("ping", {"type": "ping", **({"_stats": detail} if detail else {})})
        elif ev["kind"] in ("text", "thinking"):
            if block_open != ev["kind"]:
                yield from close_block()
                start_block = (
                    {"type": "text", "text": ""}
                    if ev["kind"] == "text"
                    else {"type": "thinking", "thinking": "", "signature": ""}
                )
                yield _sse(
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
            yield _sse(
                "content_block_delta",
                {"type": "content_block_delta", "index": index, "delta": delta},
            )
        elif ev["kind"] == "tool_use":
            yield from close_block()
            yield _sse(
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
            yield _sse(
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
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
            index += 1
        else:
            stop_reason = ev["stop_reason"]
            usage = {"input_tokens": ev["input_tokens"], "output_tokens": ev["output_tokens"]}

    yield from close_block()
    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": usage,
        },
    )
    yield _sse("message_stop", {"type": "message_stop"})


def _stream_safe(req: MessagesRequest, thread: str = "main") -> Iterator[str]:
    """Wrap _stream so server-side failures become an SSE error event the SDK
    can raise cleanly, instead of an aborted chunked response
    (httpx: 'peer closed connection without sending complete message body')."""
    try:
        yield from _stream(req, thread)
    except Exception as exc:
        log.exception("error during streaming generation")
        yield _sse(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": f"{type(exc).__name__}: {exc}"},
            },
        )


@app.post("/v1/messages")
def messages(req: MessagesRequest, request: Request):
    if (err := _validate(req)) is not None:
        return err
    # Each conversation thread (main agent + each subagent) gets its own KV
    # cache slot + continuation memo, keyed by this header.
    thread = request.headers.get("x-agent-thread", "main")
    if req.stream:
        return StreamingResponse(
            _stream_safe(req, thread),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    return _complete(req, thread)
