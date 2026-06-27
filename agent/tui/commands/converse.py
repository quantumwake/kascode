"""/converse — hands-free voice conversation with the agent (turn-based).

Loop: listen (VAD ends the turn when you stop talking) → transcribe → show it →
run the normal agent turn → speak the reply → listen again. Strictly one party
at a time: it won't listen while thinking or speaking, so you don't trip over
each other. Say "stop listening" or run /converse again to end.

Replies are kept short + spoken (a voice directive on the first turn); full
barge-in / interruption is a later phase.
"""

import pathlib
import tempfile
import threading
import time

from rich.text import Text

from ...adapters.audio.record import record
from ...adapters.audio.stt import preload, transcribe, whisper_available
from .base import Command

VOICE_DIRECTIVE = (
    "\n\n[You are in a live VOICE conversation. Reply in 1–2 short, natural "
    "spoken sentences — no markdown, no code blocks, no lists, just talk. Do any "
    "needed tool work quietly and report the result in one sentence.]"
)
STOP_PHRASES = {"stop", "stop listening", "exit voice", "end conversation", "goodbye"}


class ConverseCommand(Command):
    name = "/converse"
    summary = "hands-free voice conversation with the agent (turn-based)"
    usage = "(toggle)"

    def run(self, app, arg: str) -> None:
        if getattr(app, "converse", False):  # already running -> stop
            app.converse = False
            app.body_write(Text("[stopping voice conversation…]", style="yellow"))
            return
        if not whisper_available():
            app.body_write(
                Text("voice→text needs mlx-whisper — run `/listen install`", style="yellow")
            )
            return
        app.converse = True
        app.tts_on = True  # speak replies
        app.body_write(
            Text("🎙 voice conversation ON — just talk. Say 'stop listening' or /converse to end.",
                 style="cyan")
        )
        threading.Thread(target=lambda: self._loop(app), daemon=True).start()

    # -- the loop ------------------------------------------------------------

    def _loop(self, app) -> None:
        threading.Thread(target=preload, daemon=True).start()  # warm the model now
        max_secs = 30
        first = True
        try:
            while getattr(app, "converse", False):
                if not self._await_idle(app):
                    break
                text, err = self._listen(app, max_secs)
                if not app.converse:
                    break
                if err:
                    self._note(app, err, "red")
                    break  # a mic/record error stops the loop (not transient)
                text = (text or "").strip()
                if len(text) < 2:
                    continue  # silence — listen again
                if text.lower().strip(" .!?") in STOP_PHRASES:
                    break
                self._note(app, f"🗣  {text}", "bold #3fb950")
                app.msg_q.put(text + (VOICE_DIRECTIVE if first else ""))
                first = False
                self._await_turn(app)
        finally:
            app.converse = False
            app.tts_on = False
            app.voice_indicator(None)
            self._note(app, "🛑 voice conversation ended", "yellow")

    def _listen(self, app, max_secs):
        wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
        app.voice_indicator("listening", conn="🎙 warming mic", work="…")

        def cue() -> None:
            app.voice_indicator("listening", conn="🔴 speak now", work="listening…")

        def on_level(lv: float) -> None:
            fill = round(lv * 12)
            bar = "█" * fill + "▁" * (12 - fill)
            app.voice_indicator("listening", conn="🔴 listening", work=bar)

        path, err = record(wav, max_secs, on_ready=cue, on_level=on_level, vad=True)
        app.voice_indicator("transcribing", conn="🎧 transcribing", work="…")
        if err:
            return "", err
        text, terr = transcribe(path)
        try:
            path.unlink()
        except OSError:
            pass
        app.voice_indicator(None)
        return (text, "") if not terr else ("", text)

    # -- turn coordination (no tripping over each other) ---------------------

    @staticmethod
    def _speaking(app) -> bool:
        ov = getattr(app, "fx_override", None)
        return bool(ov and ov.get("mode") == "speaking")

    def _await_idle(self, app) -> bool:
        """Block until the agent is idle and not speaking. False if stopped."""
        while app.busy or self._speaking(app):
            if not app.converse:
                return False
            time.sleep(0.1)
        return app.converse

    def _await_turn(self, app) -> None:
        """After submitting, wait for the turn to start, finish, and stop speaking."""
        t0 = time.monotonic()
        while not app.busy and time.monotonic() - t0 < 5:
            if not app.converse:
                return
            time.sleep(0.05)
        while app.busy:
            if not app.converse:
                return
            time.sleep(0.1)
        while self._speaking(app):
            if not app.converse:
                return
            time.sleep(0.1)

    @staticmethod
    def _note(app, msg: str, style: str) -> None:
        try:
            app.call_from_thread(app.body_write, Text(msg, style=style))
        except Exception:
            try:
                app.body_write(Text(msg, style=style))
            except Exception:
                pass
