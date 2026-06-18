"""The tool-execution port: how the core loop runs a tool call and checkpoints
the workspace. Adapter: ToolRunner.
"""

from typing import Protocol


class ToolExecutor(Protocol):
    # opt-in capabilities the loop reads to decide which tool schemas to send
    net: bool
    rag: bool
    # the model's native context window, for the overflow-safety compaction
    context_limit: int | None

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Execute a tool; return (output, is_error)."""
        ...

    def checkpoint(self, label: str) -> str | None:
        """Commit this turn's workspace changes; return the short sha or None."""
        ...
