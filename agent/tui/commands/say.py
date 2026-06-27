"""/say [on|off|stop] — speak assistant replies aloud (text→voice)."""

from rich.text import Text

from ...adapters.audio import tts
from .base import Command


class SayCommand(Command):
    name = "/say"
    summary = "toggle speaking assistant replies aloud (text→voice)"
    usage = "[on|off|stop]"
    subcommands = (
        ("on", "speak replies"),
        ("off", "stop speaking replies"),
        ("stop", "cut off the current utterance"),
        ("install", "install mlx-audio for neural voices (native say/espeak work already)"),
    )

    def run(self, app, arg: str) -> None:
        arg = arg.strip().lower()
        if arg == "install":
            from ._install import install_capability

            install_capability(app, "tts-neural")
            return
        if arg == "stop":
            tts.stop()
            app.body_write(Text("[speech stopped]", style="cyan"))
            return
        if arg in ("on", "off"):
            app.tts_on = arg == "on"
        else:
            app.tts_on = not app.tts_on
        if app.tts_on and not tts.available():
            app.tts_on = False
            app.body_write(
                Text(
                    "no TTS engine available (macOS `say` / Linux espeak-ng / mlx-audio)",
                    style="yellow",
                )
            )
            return
        state = "ON — replies spoken aloud" if app.tts_on else "OFF"
        app.body_write(Text(f"text→voice {state}", style="cyan"))
