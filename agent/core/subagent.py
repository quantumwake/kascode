"""SubagentIO — an AgentIO decorator that routes a subagent's turn through the
parent IO, visually demoted, capturing full detail to a buffer for later
drill-in. It depends only on the AgentIO port (it wraps a parent io), so it
lives in the core rather than a UI adapter.
"""

import json


class SubagentIO:
    """Routes a subagent's turn through the parent IO, visually demoted.

    Confirmations still go to the user; steering stays with the main thread.
    Full subagent output (thinking/text/tools) is CAPTURED into self.buffer for
    later inspection (the TUI's /subagent drill-in); only compact markers leak
    to the parent's main view so it stays readable.
    """

    def __init__(self, parent, label: str = "", n: int = 0) -> None:
        self.parent = parent
        self.label = label
        self.n = n
        self.status = "running"
        self.buffer: list[str] = []  # captured transcript lines
        self._line = ""

    def _cap(self, text: str) -> None:
        self._line += text
        while "\n" in self._line:
            ln, self._line = self._line.split("\n", 1)
            self.buffer.append(ln)

    def _flush(self) -> None:
        if self._line:
            self.buffer.append(self._line)
            self._line = ""

    @property
    def last_decode_tps(self) -> float:
        return getattr(self.parent, "last_decode_tps", 0.0)

    def stream_started(self):
        self.parent.stream_started()

    def stream_finished(self, usage):
        self._flush()
        self.parent.stream_finished(usage)

    def delta(self, kind: str, text: str, viz=None):
        self._cap(text)  # full detail → buffer only (keeps the main view clean)

    def tool_call(self, name: str, args: dict):
        self._flush()
        self.buffer.append(f"→ {name}({json.dumps(args, ensure_ascii=False)[:160]})")
        self.parent.tool_call(f"sub[{self.n}]:{name}", args)  # compact line in main view

    def tool_result(self, output: str, is_error: bool):
        self.buffer.append(("✗ " if is_error else "✓ ") + (output[:400]))

    def notice(self, text: str):
        self.buffer.append(text)

    def confirm(self, command: str):
        return self.parent.confirm(command)

    def drain_steers(self) -> list[str]:
        return []  # steering belongs to the main thread

    def should_abort(self) -> bool:
        return self.parent.should_abort()

    def should_pause(self) -> bool:
        return self.parent.should_pause()

    def clear_abort(self) -> None:
        self.parent.clear_abort()
