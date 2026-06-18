"""Incremental output parser: model token stream -> text / thinking deltas and
tool calls. Marker vocabulary and tool-body syntax come from the dialect.
"""

from typing import Any

from .dialects import GemmaDialect
from .wire import Event, Schemas


def _safe_len(buf: str, markers: tuple[str, ...]) -> int:
    """Length of the prefix that cannot be part of a marker starting at the tail."""
    n = len(buf)
    best = n
    for m in markers:
        for k in range(min(len(m), n), 0, -1):
            if m.startswith(buf[n - k :]):
                best = min(best, n - k)
                break
    return best


class StreamParser:
    """Splits incremental model output into text / thinking deltas and tool calls.

    Marker vocabulary and tool-body syntax come from the dialect. feed()
    returns events safe to emit now; flush() drains the remainder after
    generation ends. Completed tool calls also accumulate in .tool_calls.
    """

    def __init__(self, dialect=None, schemas: Schemas | None = None, thinking: bool = False) -> None:
        self.dialect = dialect or GemmaDialect()
        self.schemas = schemas
        self.buffer = ""
        # text | think_header (gemma channel-name line) | think | tool_call
        self.state = self.dialect.initial_state(thinking)
        self.tool_calls: list[dict[str, Any]] = []
        self._text_markers = tuple(self.dialect.text_markers)
        self._skip_newlines = False  # swallow newlines after a think close

    def _tool_event(self, body: str) -> list[Event]:
        try:
            call = self.dialect.parse_tool_body(body, self.schemas)
        except (ValueError, IndexError):
            # Malformed call: surface it as visible text rather than dropping it.
            return [("text", self.dialect.wrap_failed_call(body))]
        self.tool_calls.append(call)
        return [("tool_use", call)]

    def feed(self, chunk: str) -> list[Event]:
        self.buffer += chunk
        out: list[Event] = []
        while True:
            buf = self.buffer
            if self.state == "text":
                if self._skip_newlines:
                    stripped = buf.lstrip("\n")
                    if not stripped:
                        self.buffer = ""
                        return out  # wait: chunk was only newlines
                    self._skip_newlines = False
                    self.buffer = buf = stripped
                hits = [(buf.find(m), m) for m in self._text_markers]
                hits = [(i, m) for i, m in hits if i != -1]
                if hits:
                    idx, marker = min(hits)
                    if buf[:idx]:
                        out.append(("text", buf[:idx]))
                    self.buffer = buf[idx + len(marker) :]
                    self.state = self.dialect.text_markers[marker]
                    continue
                safe = _safe_len(buf, self._text_markers)
                if buf[:safe]:
                    out.append(("text", buf[:safe]))
                self.buffer = buf[safe:]
                return out
            if self.state == "think_header":
                nl = buf.find("\n")
                if nl == -1:
                    return out  # wait for the channel name line
                self.buffer = buf[nl + 1 :]
                self.state = "think"
                continue
            if self.state == "think":
                close = self.dialect.think_close
                idx = buf.find(close)
                if idx != -1:
                    if buf[:idx]:
                        out.append(("thinking", buf[:idx]))
                    self.buffer = buf[idx + len(close) :]
                    self.state = "text"
                    self._skip_newlines = True
                    continue
                safe = _safe_len(buf, (close,))
                if buf[:safe]:
                    out.append(("thinking", buf[:safe]))
                self.buffer = buf[safe:]
                return out
            # tool_call
            close = self.dialect.tool_close
            idx = buf.find(close)
            if idx == -1:
                # Buffer until the close marker. A tool body can be large (e.g. a
                # Write of a whole file), so this yields no events for a while —
                # the server's wall-clock keep-alive ping covers that silence.
                return out
            out.extend(self._tool_event(buf[:idx]))
            self.buffer = buf[idx + len(close) :]
            self.state = "text"

    def flush(self) -> list[Event]:
        buf, self.buffer = self.buffer, ""
        state, self.state = self.state, "text"
        if not buf.strip():
            return []
        if state == "think":
            return [("thinking", buf)]
        if state == "tool_call":
            # Unterminated call (e.g. hit max_tokens): try to parse anyway.
            return self._tool_event(buf)
        return [("text", buf)]
