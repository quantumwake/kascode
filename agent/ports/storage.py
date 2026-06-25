"""The session-store port: persist the running transcript (autosaved per turn,
resumable) and compaction archives. Adapter: SessionStore (filesystem).

The composition root injects a store; core/compaction and the TUI depend only on
this contract — the instance interface, not the sessions()/resume() factories
(those are composition-root concerns). runtime_checkable so conformance is
testable.
"""

import pathlib
from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionStorePort(Protocol):
    id: str
    dir: pathlib.Path

    def save_transcript(self, messages: list, model: str | None, paused: bool) -> None: ...

    def save_compaction(
        self, original_messages: list, summary: str, meta: dict
    ) -> pathlib.Path: ...
