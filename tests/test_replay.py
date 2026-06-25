"""Resume replay: AgentApp._replay_transcript re-renders the restored
conversation into the work view (so --resume shows the full prior text, not a
blank panel). Drives the method with a fake self holding restored JSON messages.
No Textual runtime, no model/server.

Run:  uv run python tests/test_replay.py
"""

import sys

sys.path.insert(0, ".")

from agent.tui.app import AgentApp


class FakeApp:
    def __init__(self, messages) -> None:
        self.messages = messages
        self.writes: list[str] = []

    def body_write(self, r) -> None:
        self.writes.append(str(getattr(r, "plain", r)))


messages = [
    {"role": "user", "content": "build a prime sieve"},
    {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "plan it"},
            {"type": "text", "text": "I'll write it."},
            {"type": "tool_use", "name": "write_file", "input": {"path": "p.py"}},
        ],
    },
    {"role": "user", "content": [{"type": "tool_result", "content": "wrote 200 chars"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
]

app = FakeApp(messages)
AgentApp._replay_transcript(app)  # unbound; only uses self.messages + self.body_write
w = app.writes

assert any("you> build a prime sieve" in x for x in w), w  # user message
assert any("plan it" in x for x in w), w  # assistant thinking
assert any("I'll write it." in x for x in w), w  # assistant text
assert any("write_file" in x and '"path": "p.py"' in x for x in w), w  # tool_use
assert any("✓ wrote 200 chars" in x for x in w), w  # tool_result
assert any("Done." in x for x in w), w  # final answer
print("replay: user + thinking + text + tool_use + tool_result all rendered")

# a tool_result error renders with the ✗ marker
err = FakeApp(
    [{"role": "user", "content": [{"type": "tool_result", "content": "boom", "is_error": True}]}]
)
AgentApp._replay_transcript(err)
assert any("✗ boom" in x for x in err.writes), err.writes
print("replay: error tool_result marked ✗")

print("all replay tests passed")
