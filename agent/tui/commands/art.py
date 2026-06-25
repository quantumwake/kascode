from rich.text import Text

from .base import Command


class ArtCommand(Command):
    name = "/art"
    summary = "toggle image generation (needs the 'art' extra)"

    def run(self, app, arg: str) -> None:
        app.runner.art = not app.runner.art
        state = "ENABLED — generate_image available" if app.runner.art else "DISABLED"
        app.body_write(
            Text(f"image generation {state} (needs the 'art' extra: uv add mflux)", style="yellow")
        )
