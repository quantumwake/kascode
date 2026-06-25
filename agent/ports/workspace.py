"""The workspace port: per-turn checkpointing of the agent's file changes.
Adapter: GitWorkspace. ToolRunner delegates checkpoint() to a workspace, so the
contract is intentionally tiny. runtime_checkable so conformance is testable.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class WorkspacePort(Protocol):
    def ready(self) -> bool: ...

    def checkpoint(self, mutated: bool, label: str) -> str | None: ...
