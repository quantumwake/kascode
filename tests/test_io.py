"""Characterization test for TuiIO's body rendering (the structured + markdown
output): turn headers, live thinking, answer text rendered as Markdown at block
boundaries, and indented tool call/result lines. Drives TuiIO with a fake app
that records calls — no Textual runtime, no threads. No model/server.

Run:  uv run python tests/test_io.py
"""

import sys

sys.path.insert(0, ".")

from rich.markdown import Markdown

from agent.tui.io import TuiIO


class FakeApp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._agent_header_pending = True  # a user message was just submitted
        self.tok_in = 0
        self.tok_out = 0

    def call_from_thread(self, fn, *a) -> None:  # marshalling is a no-op in the test
        fn(*a)

    def body_write(self, r) -> None:
        kind = "md" if isinstance(r, Markdown) else "text"
        self.calls.append((kind, getattr(r, "plain", str(r))))

    def turn_rule(self, label: str, color: str) -> None:
        self.calls.append(("rule", label))


app = FakeApp()
io = TuiIO(app)

io.stream_started()
io.delta("thinking", "let me think...\n")  # streams live (dim)
io.delta("text", "# Plan\n\n**do** it with `code`\n")  # buffered for markdown
io.tool_call("bash", {"command": "ls"})  # flush answer as Markdown, then the call
io.tool_result("file1\nfile2", False)
io.stream_finished(None)

kinds = [(k, v[:24]) for k, v in app.calls]

# the "kas" turn header is written before the first agent output, once
assert ("rule", "kas") == (app.calls[0][0], app.calls[0][1]), kinds
assert sum(1 for k, v in app.calls if k == "rule" and v == "kas") == 1, kinds
# thinking streamed live as plain text
assert ("text", "let me think...") in app.calls, kinds
# the answer text was rendered as a Markdown renderable (not raw text)
assert any(k == "md" for k, _ in app.calls), kinds
# tool call + result are indented with the ▸ / ✓ markers
assert any(k == "text" and "▸ bash" in v for k, v in app.calls), kinds
assert any(k == "text" and "✓ file1" in v for k, v in app.calls), kinds
print("tui rendering: header + live thinking + markdown answer + tool lines OK")

# a turn that's only tool calls renders no empty Markdown block
app2 = FakeApp()
io2 = TuiIO(app2)
io2.stream_started()
io2.tool_call("read_file", {"path": "x"})
io2.stream_finished(None)
assert not any(k == "md" for k, _ in app2.calls), app2.calls  # no empty answer rendered
print("empty-answer turn: no stray markdown OK")

print("all io tests passed")
