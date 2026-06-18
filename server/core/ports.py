"""Ports — the protocols the server core depends on, so the domain logic
(continuation, the generate->events pipeline) never imports a concrete engine.
The MLX engine in server/engine.py is the driven adapter that satisfies these.
"""

from typing import Any, Iterator, Protocol


class DialectLike(Protocol):
    name: str
    supports_continuation: bool

    def continuation_tail(
        self, results: list[tuple[str, str]], texts: list[str], thinking: bool
    ) -> str | None: ...


class EngineLike(Protocol):
    """The slice of the inference engine the core uses."""

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
    ) -> Iterator[Any]: ...
