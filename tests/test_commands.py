"""Characterization tests for AgentApp.on_input_submitted — the TUI slash-command
dispatcher (153 lines, ~55 branches). Locks the routing CONTRACT before Phase 3
extracts it into a command registry. Drives the method with a lightweight fake
`self` (no Textual runtime), covering the routing that doesn't depend on mounted
widgets: confirmation routing, flag toggles, queue dispatch, steering, and paste
attach. The widget-backed commands (/fx, /theme, /stats, /model, /subagent) move
into the registry in Phase 3 and are covered there.

Run:  uv run python tests/test_commands.py
"""

import queue
import sys
import types

sys.path.insert(0, ".")

from agent.tui.commands import CommandHandler


class FakeRunner:
    def __init__(self) -> None:
        self.yolo = False
        self.rag = True
        self.net = False
        self.art = False


class FakeIO:
    def __init__(self) -> None:
        self.confirm_q: queue.Queue = queue.Queue()
        self.steer_q: queue.Queue = queue.Queue()


class FakeApp(CommandHandler):
    """Subclasses the real CommandHandler mixin so on_input_submitted +
    _dispatch_command + the _cmd_* handlers run for real; only the app's
    infrastructure (body_write/exit/state) is stubbed. The widget-backed
    commands (/fx, /theme, /stats) aren't exercised here (they need query_one)."""

    def __init__(self, busy=False, confirming=False, messages=None) -> None:
        self.confirming = confirming
        self.busy = busy
        self._pastes: list[str] = []
        self.runner = FakeRunner()
        self.io = FakeIO()
        self.messages = messages if messages is not None else []
        self.subagents: list = []
        self.model = "m"
        self.workdir = "/w"
        self.turns = 0
        self.msg_q: queue.Queue = queue.Queue()
        self.exited = False
        self.writes: list[str] = []

    def body_write(self, renderable) -> None:
        self.writes.append(str(renderable))

    def exit(self) -> None:
        self.exited = True


def _event(value: str):
    return types.SimpleNamespace(value=value, input=types.SimpleNamespace(value="sentinel"))


def fire(app: FakeApp, value: str) -> FakeApp:
    ev = _event(value)
    app.on_input_submitted(ev)
    assert ev.input.value == "", "the input box must be cleared on submit"
    return app


# 1. confirmation mode routes the line to confirm_q and does NOT dispatch
app = FakeApp(confirming=True)
fire(app, "y")
assert app.io.confirm_q.get_nowait() == "y"
assert not app.writes
print("confirmation routing: OK")

# 2. empty input is ignored
app = FakeApp()
fire(app, "")
assert app.msg_q.empty() and not app.writes
print("empty input ignored: OK")

# 3. exit / quit terminate
for word in ("exit", "quit"):
    app = FakeApp()
    fire(app, word)
    assert app.exited, word
print("exit/quit: OK")

# 4. /yolo toggles the runner flag and announces both states
app = FakeApp()
fire(app, "/yolo")
assert app.runner.yolo is True and any("yolo ON" in w for w in app.writes)
fire(app, "/yolo")
assert app.runner.yolo is False
print("/yolo toggle: OK")

# 5. /compact: idle+messages queues the sentinel; busy/empty just notify
app = FakeApp(messages=[{"role": "user", "content": "x"}])
fire(app, "/compact")
assert app.msg_q.get_nowait() == "\x00compact"

app = FakeApp()  # nothing to compact
fire(app, "/compact")
assert app.msg_q.empty() and any("nothing to compact" in w for w in app.writes)

app = FakeApp(busy=True, messages=[{"role": "user", "content": "x"}])  # busy
fire(app, "/compact")
assert app.msg_q.empty() and any("wait until the agent is idle" in w for w in app.writes)
print("/compact gating: OK")

# 6. /self-skill queues its sentinel when idle
app = FakeApp()
fire(app, "/self-skill")
assert app.msg_q.get_nowait() == "\x00self-skill"
print("/self-skill: OK")

# 7. /status prints session state
app = FakeApp()
fire(app, "/status")
assert any("yolo=" in w and "rag=" in w for w in app.writes)
print("/status: OK")

# 8. an unknown slash command prints the help menu (generated from the registry)
app = FakeApp()
fire(app, "/bogus")
assert any("Tab to autocomplete" in w for w in app.writes)  # the menu header
assert any("/spec" in w for w in app.writes)  # commands listed with summaries
print("unknown command help: OK")

# 9. a normal message while idle -> a real user turn (msg_q)
app = FakeApp()
fire(app, "build the thing")
assert app.msg_q.get_nowait() == "build the thing"
print("normal message -> msg_q: OK")

# 10. a normal message while busy -> the steering queue, not a new turn
app = FakeApp(busy=True)
fire(app, "also add tests")
assert app.io.steer_q.get_nowait() == "also add tests"
assert app.msg_q.empty() and any("queued steering" in w for w in app.writes)
print("steering while busy: OK")

# 11. staged paste attaches to the typed instruction (and bypasses slash dispatch)
app = FakeApp()
app._pastes = ["pasted blob"]
fire(app, "use this")
sent = app.msg_q.get_nowait()
assert "use this" in sent and "pasted blob" in sent
print("paste attach: OK")

print("all command tests passed")
