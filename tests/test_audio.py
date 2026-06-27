"""Voice→text adapter: ffmpeg record-command construction and transcription
gating. No mic or model — the interactive capture/transcribe paths are mocked.

Run:  uv run python tests/test_audio.py
"""

import sys

sys.path.insert(0, ".")

from agent.adapters.audio import record as rec
from agent.adapters.audio import stt

# record_command: 16 kHz mono, time-limited, platform input format.
cmd = rec.record_command("/tmp/x.wav", 5)
if cmd is not None:  # None only on an unknown OS
    assert cmd[0] == "ffmpeg" and "/tmp/x.wav" in cmd
    assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "16000"
    assert "-ac" in cmd and cmd[cmd.index("-ac") + 1] == "1"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "5"
    assert any(f in cmd for f in ("avfoundation", "pulse"))
print("record_command: OK")

# record() degrades when ffmpeg is missing (simulate via PATH lookup miss).
orig_which = rec.shutil.which
rec.shutil.which = lambda _name: None
try:
    path, err = rec.record("/tmp/x.wav", 1)
    assert path is None and "ffmpeg" in err, (path, err)
finally:
    rec.shutil.which = orig_which
print("record ffmpeg-missing: OK")


# transcribe(): missing mlx-whisper -> graceful error, not a raise.
if not stt.whisper_available():
    text, is_err = stt.transcribe("/nonexistent.wav")
    assert is_err and "mlx-whisper" in text, (text, is_err)
    print("transcribe missing-dep: OK")
else:
    # Installed: a missing file is reported, still no raise.
    text, is_err = stt.transcribe("/definitely/not/here.wav")
    assert is_err and "no audio file" in text, (text, is_err)
    print("transcribe missing-file: OK")

# transcribe() now goes through the persistent Transcriber (a serve-mode worker
# subprocess). Stub the subprocess with a fake that speaks the serve protocol:
# emits {"ready"} on spawn, then {"transcribing"}+{"done"} after a wav is written.
import json  # noqa: E402
import tempfile  # noqa: E402

import agent.adapters.audio.transcriber as trans  # noqa: E402

stt.importlib.util.find_spec = lambda name: object() if name == "mlx_whisper" else None
wav = tempfile.mktemp(suffix=".wav")
open(wav, "wb").close()


class _FakeServe:
    """Acts as the Popen handle AND its stdin/stdout: ready first, then a
    transcript per wav written to stdin."""

    def __init__(self, done_text="  hello world ", error=None):
        self._done_text, self._error = done_text, error
        self._q = ['{"event": "ready"}\n']
        self.returncode = None

    # stdin
    def write(self, s):
        if self._error is not None:
            self._q.append(json.dumps({"event": "error", "msg": "Trace\n" + self._error}) + "\n")
        else:
            self._q.append('{"event": "transcribing", "audio_secs": 1.0}\n')
            self._q.append(json.dumps({"event": "done", "text": self._done_text}) + "\n")
        return len(s)

    def flush(self):
        pass

    # process handle
    def poll(self):
        return None  # alive

    def kill(self):
        self.returncode = -9

    # streams (stdin and stdout are both this object)
    stdin = property(lambda self: self)
    stdout = property(lambda self: self)

    def __iter__(self):
        return self

    def __next__(self):
        if self._q:
            return self._q.pop(0)
        raise StopIteration


stt._TRANSCRIBER = None
_orig_trans_popen = trans.subprocess.Popen
trans.subprocess.Popen = lambda *a, **k: _FakeServe()
try:
    seen = []
    text, is_err = stt.transcribe(wav, on_progress=lambda e: seen.append(e["event"]))
    assert not is_err and text == "hello world", (text, is_err)
    assert seen == ["transcribing"], seen  # ready consumed at spawn; done at end
    # a worker error surfaces with the last traceback line
    stt._TRANSCRIBER = None
    trans.subprocess.Popen = lambda *a, **k: _FakeServe(error="ValueError: boom")
    text, is_err = stt.transcribe(wav)
    assert is_err and "boom" in text, (text, is_err)
finally:
    stt._TRANSCRIBER = None
    trans.subprocess.Popen = _orig_trans_popen  # restore (it's the global module)
print("transcribe via warm worker (stubbed): OK")


# --- text→voice (TTS) -------------------------------------------------------
from agent.adapters.audio import tts  # noqa: E402

# native command building per OS (macOS say / linux espeak family) or None.
cmd = tts._native_cmd("hello world")
assert cmd is None or (cmd[0] in ("say", "espeak-ng", "espeak", "spd-say") and "hello world" in cmd)
print("tts native_cmd: OK")

# speak() with no engine -> graceful error; with a stubbed Popen -> launches.
orig_native = tts._native_cmd
orig_mlx = tts._mlx_available
tts._native_cmd = lambda _t: None
tts._mlx_available = lambda: False
try:
    msg, is_err = tts.speak("hi")
    assert is_err and "TTS" in msg, (msg, is_err)
finally:
    tts._native_cmd = orig_native
    tts._mlx_available = orig_mlx

launched = {}
orig_popen = tts.subprocess.Popen
tts._native_cmd = lambda t: ["true", t]


def _fake_popen(cmd, **kw):
    launched["cmd"] = cmd
    return type("P", (), {"poll": lambda self: None, "terminate": lambda self: None})()


tts.subprocess.Popen = _fake_popen
try:
    msg, is_err = tts.speak("speak this")
    assert not is_err and launched["cmd"] == ["true", "speak this"], (msg, launched)
    # empty text is a no-op success
    assert tts.speak("   ") == ("", False)
finally:
    tts._native_cmd = orig_native
    tts.subprocess.Popen = orig_popen
print("tts speak: OK")

# _reply_text pulls the last assistant text out of a transcript (for /say).
from agent.tui.loops import WorkerLoops  # noqa: E402

msgs = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": [{"type": "text", "text": "hello there"}]},
    {"role": "user", "content": "bye"},
    {"role": "assistant", "content": "goodbye now"},
]
assert WorkerLoops._reply_text(msgs) == "goodbye now"
assert WorkerLoops._reply_text(msgs[:2]) == "hello there"
assert WorkerLoops._reply_text([{"role": "user", "content": "x"}]) == ""
print("tts reply_text: OK")


# --- wav decode (the fds_to_keep fix: hand whisper samples, not a path) ------
import pathlib  # noqa: E402
import wave  # noqa: E402

import numpy as np  # noqa: E402

from agent.adapters.audio.stt import _load_wav_16k_mono, model_present  # noqa: E402

wav = tempfile.mktemp(suffix=".wav")
samp = (0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, 0.5, 8000, endpoint=False)) * 32767).astype(
    np.int16
)
with wave.open(wav, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(samp.tobytes())
arr = _load_wav_16k_mono(pathlib.Path(wav))
assert arr.dtype == np.float32 and len(arr) == 8000 and -1.0 <= arr.min() and arr.max() <= 1.0
# stereo @ 8 kHz downmixes to mono and resamples to 16 kHz
wav2 = tempfile.mktemp(suffix=".wav")
st = np.repeat(samp[:4000, None], 2, axis=1)
with wave.open(wav2, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(st.tobytes())
arr2 = _load_wav_16k_mono(pathlib.Path(wav2))
assert arr2.ndim == 1 and abs(len(arr2) - 8000) <= 2
assert isinstance(model_present(), bool)
print("wav decode + model_present: OK")


# --- voice indicator override (owns the live bar during /listen + /say) ------
from agent.tui.app import AgentApp  # noqa: E402


class IndApp:
    def __init__(self):
        self.fx_mode = "idle"
        self.fx_override = None


app = IndApp()
AgentApp.voice_indicator(app, "listening", conn="🎙 listening", work="5s")
assert app.fx_override["mode"] == "listening" and app.fx_mode == "listening"
assert app.fx_override["conn"] == "🎙 listening"
AgentApp.voice_indicator(app, None)  # release
assert app.fx_override is None
print("voice_indicator: OK")

print("all audio tests passed")
