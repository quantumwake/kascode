"""/listen [seconds] — record from the mic and transcribe into the input box."""

import pathlib
import tempfile
import threading
import time

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
        # Warm the model NOW, overlapped with the recording window — so by the
        # time we transcribe it's already loaded (instant on later /listens).
        from ...adapters.audio.stt import preload

        threading.Thread(target=preload, daemon=True).start()

        def worker() -> None:
            wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
            app.voice_indicator("listening", conn="🎙 warming mic", work="…")

            def cue_ready() -> None:  # fired once the mic is actually hot
                app.voice_indicator("listening", conn="🔴 speak now", work="▁▁▁▁▁▁▁▁▁▁▁▁")
                self._note(app, "🔴 speak now", "green")

            def on_level(lv: float) -> None:  # live voice meter (0..1)
                fill = round(lv * 12)
                bar = "█" * fill + "▁" * (12 - fill)
                app.voice_indicator("listening", conn="🔴 listening", work=bar)

            path, err = record(wav, secs, on_ready=cue_ready, on_level=on_level)
            if err:
                app.voice_indicator(None)
                self._note(app, err, "red")
                return
            from ...adapters.audio.stt import model_present

            # A ticking elapsed counter + phase = visible "movement" while the
            # (out-of-process) transcriber loads the model and decodes.
            first_run = not model_present()
            state = {"phase": "downloading model (first run)" if first_run else "loading model"}
            if first_run:
                self._note(app, "🎧 first run: downloading whisper model (~1.5 GB)…", "cyan")
            done = threading.Event()
            t0 = time.monotonic()

            def tick() -> None:
                while not done.wait(0.5):
                    el = int(time.monotonic() - t0)
                    app.voice_indicator("transcribing", conn="🎧 " + state["phase"], work=f"{el}s")

            def progress(ev: dict) -> None:
                k = ev.get("event")
                if k == "loading":
                    state["phase"] = "loading model"
                elif k == "transcribing":
                    state["phase"] = f"transcribing {ev.get('audio_secs', '?')}s clip"
                elif k == "segment":
                    state["phase"] = f"transcribing · segment {ev.get('n')}"

            app.voice_indicator("transcribing", conn="🎧 " + state["phase"], work="0s")
            threading.Thread(target=tick, daemon=True).start()
            text, is_err = transcribe(path, on_progress=progress)
            done.set()
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
