from rich.text import Text

from .base import Command


class StatusCommand(Command):
    name = "/status"
    summary = "show model / yolo / rag / net / workdir / turns"

    def run(self, app, arg: str) -> None:
        app.body_write(
            Text(
                f"model={app.model}  yolo={app.runner.yolo}  rag={app.runner.rag}  "
                f"net={app.runner.net}  workdir={app.workdir}  turns={app.turns}",
                style="yellow",
            )
        )
