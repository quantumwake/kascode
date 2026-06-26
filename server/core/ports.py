"""Ports — the protocols the server core depends on, so the domain logic
(continuation, the generate->events pipeline) never imports a concrete engine.

A backend is any class satisfying EngineLike: the MLX one lives in
server/backends/mlx.py, but the core knows only this contract, so a llama.cpp
(GGUF), CUDA, or ROCm backend is a new adapter here, not a core change. The types
in this module are backend-neutral — GenChunk is what every backend's generate()
yields, regardless of the underlying runtime.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class GenChunk:
    """One unit emitted by a backend's generate() stream. Backend-neutral: any
    engine (MLX, llama.cpp, …) yields these; the pipeline renders them to wire
    events without knowing the runtime."""

    text: str
    done: bool = False
    ping: bool = False  # keep-alive heartbeat (no content), not a real token
    prompt_tokens: int = 0  # full prompt length (for usage)
    cached_tokens: int = 0  # prefix served from the KV cache
    generation_tokens: int = 0
    prompt_tps: float = 0.0
    generation_tps: float = 0.0
    peak_memory: float = 0.0  # GB
    finish_reason: str | None = None  # "stop" | "length" | "stop_sequence"
    # Per-token logprob summary for /viz (only when the client asked, via the
    # x-agent-viz header): {"conf": float, "entropy": float, "top": [[tok, prob]…]}.
    viz: dict | None = None


class DialectLike(Protocol):
    name: str
    supports_continuation: bool

    def continuation_tail(
        self, results: list[tuple[str, str]], texts: list[str], thinking: bool
    ) -> str | None: ...


class EngineLike(Protocol):
    """The full inference-backend contract the server depends on — what any
    backend (MLX, llama.cpp/GGUF, CUDA, …) must implement. Two groups: the
    inference slice the core uses (tokenize/encode/cache_snapshot/generate +
    model_id/dialect/stats) and the management ops the HTTP layer drives
    (swap/request_cancel/ping_status, plus optional rehydrate)."""

    model_id: str
    dialect: DialectLike
    stats: dict[str, Any]

    def tokenize(
        self,
        chat_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
    ) -> list[int]: ...

    def encode(self, text: str) -> list[int]: ...

    def cache_snapshot(self, cache_key: str = "main") -> list[int]: ...

    def generate(
        self,
        prompt_tokens: list[int],
        max_tokens: int,
        temperature: float | None,
        top_p: float | None,
        stop_sequences: list[str],
        cache_key: str = "main",
        persist_dir: str | None = None,
        viz: bool = False,  # emit per-token logprob summaries on GenChunk.viz (for /viz)
    ) -> Iterator[GenChunk]: ...

    # -- server management (driven by the HTTP layer, not the core) --
    def swap(self, model_id: str) -> None:
        """Hot-swap the served model; blocks until loaded (or raises)."""
        ...

    def request_cancel(self) -> bool:
        """Interrupt the in-flight generation; True if one was active."""
        ...

    def ping_status(self) -> dict[str, Any]:
        """Keep-alive ping bookkeeping (count + last timestamp) for GET /v1/stats."""
        ...

    # Optional (KV-resume): rehydrate a thread's cache from disk. Backends that
    # don't support it simply omit it; callers guard with getattr/try.
    def rehydrate(self, thread: str, persist_dir: str) -> str: ...
