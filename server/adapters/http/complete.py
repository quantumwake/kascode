"""Non-streaming /v1/messages: aggregate the event stream into one Anthropic
Messages response body."""

import uuid
from typing import Any

from fastapi.responses import JSONResponse

from ...core.pipeline import run
from ...core.ports import EngineLike
from ...schema import MessagesRequest


def complete(
    req: MessagesRequest,
    engine: EngineLike,
    memos: dict[str, dict],
    thread: str = "main",
    persist_dir: str | None = None,
) -> JSONResponse:
    content: list[dict[str, Any]] = []
    stop_reason, usage = "end_turn", {"input_tokens": 0, "output_tokens": 0}
    for ev in run(req, engine, memos, thread, persist_dir):
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
