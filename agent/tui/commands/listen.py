"""/listen [seconds] — record from the mic and transcribe into the input box."""

import pathlib
import tempfile
import threading

from rich.text import Text
from textual.widgets import Input

from ...adapters.audio.record import record
from ...adapters.audio.stt import transcribe, whisper_available
from .base import Command


class ListenCommand(Command):
    name = "/listen"
    summary = "record from the mic and transcribe to the input box (voice→text)"
    usage = "[seconds|install]"
    subcommands = (("install", "install mlx-whisper for voice→text"),)

    def run(self, app, arg: str) -> None:
        if arg.strip().lower() == "install":
            from ._install import install_capability

            install_capability(app, "voice")
            return
        if not whisper_available():
            app.body_write(
                Text(
                    "voice→text needs mlx-whisper — run `/listen install` (Apple Silicon)",
                    style="yellow",
                )
            )
            return
        secs = int(arg) if arg.strip().isdigit() else 5
        secs = max(1, min(secs, 120))
        app.body_write(Text(f"🎙  listening for {secs}s…", style="cyan"))
        app.voice_indicator("listening", conn="🎙 listening", work=f"{secs}s")

        def worker() -> None:
            wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
            path, err = record(wav, secs)
            if err:
                app.voice_indicator(None)
                self._note(app, err, "red")
                return
            # First run pulls the whisper model (silent + slow), so say so.
            from ...adapters.audio.stt import model_present

            note = "transcribing…" if model_present() else "downloading whisper model (first run)…"
            app.voice_indicator("transcribing", conn="🎧 transcribing", work=note)
            self._note(app, f"🎧 {note}", "cyan")
            text, is_err = transcribe(path)
            app.voice_indicator(None)  # release the indicator
            try:
                path.unlink()
            except OSError:
                pass
            if is_err:
                self._note(app, text, "red")
            elif not text:
                self._note(app, "(heard nothing)", "yellow")
            else:
                self._insert(app, text)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _note(app, msg: str, style: str) -> None:
        try:
            app.call_from_thread(app.body_write, Text(msg, style=style))
        except Exception:
            pass

    @staticmethod
    def _insert(app, text: str) -> None:
        def do() -> None:
            inp = app.query_one(Input)
            inp.value = f"{inp.value} {text}".strip() if inp.value else text
            app.body_write(Text(f"📝 {text}", style="green"))

        try:
            app.call_from_thread(do)
        except Exception:
            pass
