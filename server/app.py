"""Anthropic Messages API-compatible server backed by a local MLX model.

Composition root: wires the MLX engine (driven adapter) to the HTTP routes
(driving adapter) and the generate->events pipeline (core). The request
translation, continuation memo, and SSE framing live in server/{prompting,core,
adapters}; this module holds only the FastAPI app, lifecycle, shared state
(the engine + per-thread continuation memos), and the route handlers.

Run:  uv run uvicorn server.app:app --port 8765

Point any official Anthropic SDK at it:

    client = anthropic.Anthropic(base_url="http://127.0.0.1:8765", api_key="local")
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from .adapters.http.complete import complete
from .adapters.http.sse import stream_safe
from .backends import make_engine
from .config import KV_PERSIST, MODEL_ID
from .core import kvpersist
from .core.continuation import echo_matches, norm_blocks, req_key, try_continuation
from .core.pipeline import run
from .core.ports import EngineLike
from .schema import MessagesRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("kas")

# Shared server state. Each conversation thread (main agent + each subagent)
# gets its own KV-cache slot (in the engine) and its own continuation memo.
# `engine` is any EngineLike backend (selected at startup), not a concrete class.
engine: EngineLike | None = None
_memos: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    try:
        from scripts.banner import print_console

        print_console(model=MODEL_ID, extra="inference server")
    except Exception:
        pass
    # Pick the backend (KAS_BACKEND, else auto-detected from the model id) —
    # MLX today, llama.cpp/CUDA/ROCm later — without the server knowing which.
    engine = make_engine(MODEL_ID)
    yield


app = FastAPI(title="kas", lifespan=lifespan)


def error_response(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "error", "error": {"type": err_type, "message": message}},
    )


# Cap request body size — a localhost guard against a single client exhausting
# memory with a multi-GB messages array. Checks Content-Length (which the
# Anthropic SDK always sends); a chunked body with no such header is not bounded
# here, which is acceptable for a local-only server. Override via env.
MAX_BODY_BYTES = int(os.environ.get("KAS_MAX_BODY_BYTES", str(64 * 1024 * 1024)))


@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl is not None and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        return error_response(
            413, "request_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes"
        )
    return await call_next(request)


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


@app.post("/v1/cancel")
def cancel_generation() -> dict[str, Any]:
    """Interrupt the in-flight generation NOW — including a long prefill (which
    otherwise can't be cancelled until it finishes). Lets a client stop quickly
    and frees the worker so a queued model swap can proceed."""
    if engine is None:
        return {"ok": False, "active": False}
    return {"ok": True, "active": engine.request_cancel()}


@app.get("/v1/stats")
def live_stats() -> dict[str, Any]:
    """Live generation progress — polled by clients while the stream is quiet
    (e.g. during a long tool call, whose body is buffered until it closes)."""
    if engine is None:
        return {"model": MODEL_ID, "active": False}
    sysstats = getattr(engine, "system_stats", lambda: {})()
    return {"model": MODEL_ID, **engine.stats, **engine.ping_status(), **sysstats}


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


@app.post("/v1/messages")
def messages(req: MessagesRequest, request: Request):
    if (err := _validate(req)) is not None:
        return err
    # Each conversation thread (main agent + each subagent) gets its own KV
    # cache slot + continuation memo, keyed by this header.
    thread = request.headers.get("x-agent-thread", "main")
    # Diagnostic: two concurrent agents MUST show different threads here. If both
    # log thread=main they're sharing a KV slot + continuation memo (e.g. an agent
    # process running pre-fix code) — restart the agents.
    log.info("turn model=%s thread=%s stream=%s", req.model, thread, req.stream)
    # /viz: when the client asks (any overlay on), the engine emits per-token
    # logprobs. Only then — the top-k+entropy compute isn't free.
    viz = bool(request.headers.get("x-agent-viz"))

    # Warm KV-resume: if persistence is on and the agent told us its session
    # dir, rehydrate this thread's KV cache + continuation memo from disk before
    # the first turn (no-op once the slot is warm in memory). Best-effort.
    persist_dir = request.headers.get("x-agent-session-dir") if KV_PERSIST else None
    if persist_dir and engine is not None:
        try:
            status = engine.rehydrate(thread, persist_dir)
            if status.startswith("rehydrated") and thread not in _memos:
                memo = kvpersist.read_json(
                    kvpersist.memo_path(kvpersist.thread_dir(persist_dir, thread))
                )
                if memo:
                    _memos[thread] = memo
        except Exception:
            log.info("kv rehydrate trigger failed; cold prefill", exc_info=True)

    if req.stream:
        return StreamingResponse(
            stream_safe(req, engine, _memos, thread, persist_dir, viz),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    return complete(req, engine, _memos, thread, persist_dir)


# --------------------------------------------------------------------------
# Back-compat shims: bind the (now-pure) core functions to this module's shared
# engine/memo state. Kept so existing tests and any external callers that
# import these private names keep working unchanged.
# --------------------------------------------------------------------------

_req_key = req_key
_norm_blocks = norm_blocks
_echo_matches = echo_matches


def _try_continuation(req: MessagesRequest, key: str, thread: str) -> list[int] | None:
    return try_continuation(req, key, thread, engine, _memos)


def _run(req: MessagesRequest, thread: str = "main"):
    return run(req, engine, _memos, thread)
