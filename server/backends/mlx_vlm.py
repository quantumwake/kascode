"""Vision-language backend (image→text) via mlx-vlm on Apple Silicon.

Selected by make_engine when the model is a VLM (model_kind == "vision") and
mlx-vlm is installed. VLMs don't fit the token-id warm-resume pipeline: the
processor fuses image patch embeddings with text, and mlx-vlm does its own
tokenization. So this engine carries the (prompt_text, images) of the current
turn as instance state — tokenize() stashes them and returns ids only for the
usage count; generate() runs mlx-vlm over the stash, ignoring prompt_tokens'
content. supports_continuation is False (set on the dialect), so the core never
asks it for a continuation tail.

mlx-vlm is an optional dep; this module is imported only after make_engine has
confirmed it's installed, so nothing here loads on a text-only setup.

NOTE: needs live validation with mlx-vlm installed + a VLM downloaded (e.g.
mlx-community/Qwen2.5-VL-7B-Instruct-4bit). The mlx-vlm API has shifted across
releases, so the generate() call sites are written defensively.
"""

import base64
import logging
import pathlib
import tempfile
import time
from collections.abc import Iterator
from typing import Any

from ..core.ports import GenChunk

log = logging.getLogger("kas")


def _resolve_images(chat_messages: list[dict[str, Any]]) -> list[str]:
    """Pull image sources out of the chat content and return local file paths.

    Accepts our two source shapes: {"type":"path","path":...} (TUI, no base64
    bloat) and {"type":"base64","media_type":...,"data":...} (wire). Base64
    images are written to temp files because mlx-vlm loads images by path/PIL.
    """
    paths: list[str] = []
    for msg in chat_messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for entry in content:
            if not isinstance(entry, dict) or entry.get("type") != "image":
                continue
            src = entry.get("source") or {}
            if src.get("type") == "path" and src.get("path"):
                paths.append(str(src["path"]))
            elif src.get("type") == "base64" and src.get("data"):
                ext = (src.get("media_type") or "image/png").split("/")[-1]
                tmp = pathlib.Path(tempfile.mktemp(suffix=f".{ext}"))
                tmp.write_bytes(base64.b64decode(src["data"]))
                paths.append(str(tmp))
    return paths


def _prompt_text(content: Any) -> str:
    """Flatten a chat message's content to plain text (image entries dropped —
    they're passed to the model separately)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(e.get("text", "") for e in content if e.get("type") == "text")
    return ""


class MlxVlmEngine:
    """EngineLike VLM backend. See module docstring for the state-carrying model."""

    def __init__(self, model_id: str) -> None:
        from mlx_vlm import load
        from mlx_vlm.utils import load_config

        from ..prompting import detect_dialect

        t0 = time.time()
        self.model_id = model_id
        self.model, self.processor = load(model_id)
        self.config = load_config(model_id)
        self.tokenizer = getattr(self.processor, "tokenizer", self.processor)
        self.dialect = detect_dialect(getattr(self.tokenizer, "chat_template", None), model_id)
        # VLM turns are re-rendered every time; never offer a continuation tail.
        self.dialect.supports_continuation = False
        self.context_length = getattr(self.config, "max_position_embeddings", None)
        self.stats: dict[str, Any] = {"active": False}
        self._pending: tuple[str, list[str]] = ("", [])
        self._cancel = False
        self.ping_count = 0
        self.last_ping_ts = 0.0
        log.info("VLM loaded in %.1fs (dialect: %s)", time.time() - t0, self.dialect.name)

    def tokenize(
        self,
        chat_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
    ) -> list[int]:
        from mlx_vlm.prompt_utils import apply_chat_template

        images = _resolve_images(chat_messages)
        prompt = apply_chat_template(
            self.processor, self.config, chat_messages, num_images=len(images)
        )
        self._pending = (prompt, images)
        return self.encode(prompt if isinstance(prompt, str) else _prompt_text(chat_messages[-1]))

    def encode(self, text: str) -> list[int]:
        try:
            return self.tokenizer.encode(text)
        except Exception:
            return []

    def cache_snapshot(self, cache_key: str = "main") -> list[int]:
        return []  # no KV warm-resume for VLMs

    def generate(
        self,
        prompt_tokens: list[int],
        max_tokens: int,
        temperature: float | None,
        top_p: float | None,
        stop_sequences: list[str],
        cache_key: str = "main",
        persist_dir: str | None = None,
        viz: bool = False,
    ) -> Iterator[GenChunk]:
        from mlx_vlm import stream_generate

        from ._gpu import gpu_guard

        prompt, images = self._pending
        self._cancel = False
        self.stats = {"active": True, "phase": "generate", "generated": 0}
        produced = 0
        t0 = time.time()
        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        try:
            # Serialize GPU work with the text engine (and other VLM requests) —
            # the VLM engine has no worker thread, so concurrent requests would
            # otherwise overlap command buffers on the one Metal device and trip
            # the GPU watchdog -> whole-server abort. Held for the whole generation.
            with gpu_guard():
                for chunk in stream_generate(self.model, self.processor, prompt, images, **kwargs):
                    if self._cancel:
                        break
                    text = getattr(chunk, "text", str(chunk))
                    produced += 1
                    self.stats["generated"] = produced
                    yield GenChunk(text=text)
        finally:
            self.stats = {"active": False}
        elapsed = time.time() - t0
        yield GenChunk(
            text="",
            done=True,
            prompt_tokens=len(prompt_tokens),
            cached_tokens=0,
            generation_tokens=produced,
            generation_tps=produced / elapsed if elapsed else 0.0,
            finish_reason="length" if produced >= max_tokens else "stop",
        )

    def swap(self, model_id: str) -> None:
        from mlx_vlm import load
        from mlx_vlm.utils import load_config

        from ..prompting import detect_dialect

        self.model, self.processor = load(model_id)
        self.config = load_config(model_id)
        self.tokenizer = getattr(self.processor, "tokenizer", self.processor)
        self.dialect = detect_dialect(getattr(self.tokenizer, "chat_template", None), model_id)
        self.dialect.supports_continuation = False
        self.model_id = model_id

    def request_cancel(self) -> bool:
        active = self.stats.get("active", False)
        self._cancel = True
        return bool(active)

    def ping_status(self) -> dict[str, Any]:
        age = round(time.monotonic() - self.last_ping_ts, 1) if self.last_ping_ts else None
        return {"pings": self.ping_count, "last_ping_age": age}
