"""/converse: toggle on/off + the turn-coordination helpers that keep the agent
and user from talking over each other. The full audio loop isn't run (no mic);
threads/record/transcribe are stubbed.

Run:  uv run python tests/test_converse.py
"""

import sys
import types

sys.path.insert(0, ".")

import agent.tui.commands.converse as conv
from agent.tui.commands.converse import STOP_PHRASES, VOICE_DIRECTIVE, ConverseCommand


class App:
    def __init__(self):
        self.writes = []
        self.converse = False
        self.tts_on = False
        self.fx_override = None
        self.busy = False

    def body_write(self, r):
        self.writes.append(str(r))


c = ConverseCommand()

# whisper unavailable -> hint, does NOT start.
conv.whisper_available = lambda: False
app = App()
c.run(app, "")
assert app.converse is False and any("mlx-whisper" in w for w in app.writes), app.writes
print("converse gate (no whisper): OK")

# whisper available -> toggles ON (stub Thread so the loop doesn't actually run).
conv.whisper_available = lambda: True
conv.threading.Thread = lambda *a, **k: types.SimpleNamespace(start=lambda: None)
app = App()
c.run(app, "")
assert app.converse is True and app.tts_on is True, (app.converse, app.tts_on)
# second invocation toggles OFF
c.run(app, "")
assert app.converse is False
print("converse toggle: OK")

# _speaking reflects the speaking indicator.
app = App()
assert c._speaking(app) is False
app.fx_override = {"mode": "speaking"}
assert c._speaking(app) is True
print("_speaking: OK")

# _await_idle bails out (False) when converse is turned off mid-wait.
app = App()
app.converse = False
assert c._await_idle(app) is False
# idle + not speaking + still on -> True
app = App()
app.converse = True
app.busy = False
assert c._await_idle(app) is True
print("_await_idle: OK")

# the voice directive enforces brevity + the stop phrases are sane.
assert "stop listening" in STOP_PHRASES and "stop" in STOP_PHRASES
assert "voice" in VOICE_DIRECTIVE.lower() and "sentence" in VOICE_DIRECTIVE.lower()
print("directive + stop phrases: OK")

print("all converse tests passed")
