from rich.text import Text

from .base import Command


class YoloCommand(Command):
    name = "/yolo"
    summary = "toggle auto-approve — run commands without confirmation"

    def run(self, app, arg: str) -> None:
        app.runner.yolo = not app.runner.yolo
        state = (
            "ON — commands run without confirmation"
            if app.runner.yolo
            else "OFF — commands need approval"
        )
        app.body_write(Text(f"yolo {state}", style="yellow"))
