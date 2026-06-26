"""Characterization tests for agent_turn() — the agentic loop. These LOCK the
loop's observable behaviour before Phase 4 splits the 232-line function, using
fakes for the three ports it depends on (the Anthropic client, the AgentIO, the
ToolExecutor). No model or server needed.

Covers: a plain text turn, the tool-call -> result -> continue loop, steering
injection at a tool boundary, dropped-connection reconnect, pause, and
keeping partial output on interrupt.

Run:  uv run python tests/test_loop.py
"""

import sys
from collections import deque

sys.path.insert(0, ".")

import agent.core.loop as loopmod
from agent.core.loop import agent_turn

# --- fake Anthropic streaming client ---------------------------------------


class FakeUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 10) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeDelta:
    def __init__(self, type: str, **kw) -> None:
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class FakeEvent:
    def __init__(self, type: str, delta=None) -> None:
        self.type = type
        self.delta = delta


class TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class ToolUseBlock:
    type = "tool_use"

    def __init__(self, id: str, name: str, input: dict) -> None:
        self.id = id
        self.name = name
        self.input = input


class FakeMessage:
    def __init__(self, content: list, stop_reason: str, usage: FakeUsage) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class FakeStream:
    def __init__(self, resp: dict) -> None:
        self.resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        if "raise" in self.resp:
            raise self.resp["raise"]
        yield from self.resp["events"]

    def get_final_message(self):
        return self.resp["message"]


class FakeMessages:
    def __init__(self, client: "FakeClient") -> None:
        self._client = client

    def stream(self, **kwargs):
        self._client.calls.append(kwargs)
        return FakeStream(self._client.script.pop(0))


class FakeClient:
    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        self.messages = FakeMessages(self)

    def with_options(self, **kw):
        return self  # ignore max_retries


def text_turn(text: str, stop: str = "end_turn") -> dict:
    return {
        "events": [FakeEvent("content_block_delta", FakeDelta("text_delta", text=text))],
        "message": FakeMessage([TextBlock(text)], stop, FakeUsage()),
    }


def tool_turn(tool_id: str, name: str, args: dict) -> dict:
    # tool_use blocks aren't streamed as text/thinking deltas in this loop
    return {
        "events": [],
        "message": FakeMessage([ToolUseBlock(tool_id, name, args)], "tool_use", FakeUsage()),
    }


# --- fake ports ------------------------------------------------------------


class FakeIO:
    def __init__(self, steers=None, abort_after=None, pause=False) -> None:
        self.last_decode_tps = 30.0
        self.deltas: list[tuple[str, str]] = []
        self.notices: list[str] = []
        self.tool_calls: list[tuple[str, dict]] = []
        self.tool_results: list[tuple[str, bool]] = []
        self.stream_starts = 0
        self.stream_finishes = 0
        self._steers = list(steers or [])
        self._abort_after = abort_after
        self._abort_calls = 0
        self._pause = pause

    def clear_abort(self):
        pass

    def stream_started(self):
        self.stream_starts += 1

    def stream_finished(self, usage):
        self.stream_finishes += 1

    def should_abort(self) -> bool:
        self._abort_calls += 1
        return self._abort_after is not None and self._abort_calls > self._abort_after

    def should_pause(self) -> bool:
        return self._pause

    def delta(self, kind: str, text: str, viz=None):
        self.deltas.append((kind, text))

    def drain_steers(self) -> list:
        s, self._steers = self._steers, []
        return s

    def notice(self, msg: str):
        self.notices.append(msg)

    def tool_call(self, name: str, args: dict):
        self.tool_calls.append((name, args))

    def tool_result(self, output: str, is_error: bool):
        self.tool_results.append((output, is_error))


class FakeRunner:
    def __init__(self, outputs=None) -> None:
        self.compact_at = 120_000
        self.rag = False
        self.net = False
        self.art = False
        self.persist_kv = False
        self.context_limit = 200_000
        self.hard_limit_frac = 0.85
        self.compact_cooldown = 0
        self.compact_floor = 0
        self.tps_valve = False  # keep classify_compaction at "none" in these tests
        self.tps_window = deque(maxlen=4)
        self.last_input_tokens = 0
        self._outputs = outputs or {}
        self.runs: list[tuple[str, dict]] = []
        self.checkpoints: list[str] = []

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        self.runs.append((name, args))
        return self._outputs.get(name, ("ok", False))

    def checkpoint(self, label: str):
        self.checkpoints.append(label)
        return None


def _run(script, messages=None, io=None, runner=None):
    io = io or FakeIO()
    runner = runner or FakeRunner()
    messages = messages if messages is not None else [{"role": "user", "content": "hi"}]
    agent_turn(FakeClient(script), messages, runner, io, model="test-model", max_tokens=1000)
    return messages, io, runner


# 1. plain text turn: stream a reply, no tools, clean finish
messages, io, runner = _run([text_turn("Let me check.")])
assert io.deltas == [("text", "Let me check.")]
assert io.stream_starts == 1 and io.stream_finishes == 1
assert not io.tool_calls and not runner.runs
assert messages[-1]["role"] == "assistant"
print("plain text turn: OK")

# 2. tool call -> result fed back -> second turn finishes
client_script = [tool_turn("t1", "bash", {"command": "ls"}), text_turn("done")]
messages, io, runner = _run(
    client_script, io=FakeIO(), runner=FakeRunner({"bash": ("file list", False)})
)
assert runner.runs == [("bash", {"command": "ls"})]
assert io.tool_calls == [("bash", {"command": "ls"})]
assert io.tool_results == [("file list", False)]
# the tool_result was fed back as a user message before the 2nd model call
assert any(m["role"] == "user" and isinstance(m["content"], list) for m in messages)
assert messages[-1]["role"] == "assistant"  # ends on the "done" reply
print("tool call -> result -> finish: OK")

# 3. steering submitted mid-run is injected at the tool boundary
io = FakeIO(steers=["focus on the tests"])
messages, io, runner = _run([tool_turn("t1", "bash", {"command": "ls"}), text_turn("ok")], io=io)
assert any("injecting 1 steering message" in n for n in io.notices), io.notices
injected = [
    m
    for m in messages
    if m["role"] == "user"
    and isinstance(m["content"], list)
    and any("focus on the tests" in str(b.get("text", "")) for b in m["content"])
]
assert injected, "steering text should be injected alongside the tool result"
print("steering injection: OK")

# 4. dropped connection reconnects (no partial shown yet) then succeeds
import httpx  # noqa: E402

_orig_sleep = loopmod.time.sleep
loopmod.time.sleep = lambda *a: None  # don't actually back off during the test
try:
    script = [{"raise": httpx.RemoteProtocolError("boom")}, text_turn("recovered")]
    messages, io, runner = _run(script)
finally:
    loopmod.time.sleep = _orig_sleep
assert any("connection dropped" in n and "reconnecting 1/3" in n for n in io.notices), io.notices
assert io.deltas == [("text", "recovered")]
print("reconnect on dropped connection: OK")

# 5. pause: abort immediately, paused -> clean return, nothing raised
io = FakeIO(abort_after=0, pause=True)
messages, io, runner = _run([text_turn("partial")], io=io)
assert any("paused" in n for n in io.notices), io.notices
print("pause: OK")

# 6. interrupt (no pause) keeps the partial output already streamed
two_deltas = {
    "events": [
        FakeEvent("content_block_delta", FakeDelta("text_delta", text="par")),
        FakeEvent("content_block_delta", FakeDelta("text_delta", text="tial")),
    ],
    "message": FakeMessage([TextBlock("partial")], "end_turn", FakeUsage()),
}
io = FakeIO(abort_after=1, pause=False)  # let the first delta through, then abort
messages, io, runner = _run([two_deltas], io=io)
assert ("text", "par") in io.deltas
assert any("interrupted" in n for n in io.notices), io.notices
# the partial assistant content was preserved on the transcript
assert messages[-1]["role"] == "assistant"
print("interrupt keeps partial: OK")

print("all loop tests passed")
