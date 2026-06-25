from rich.text import Text

from .base import Command


class KvCommand(Command):
    name = "/kv"
    summary = "show the KV-cache status"

    def run(self, app, arg: str) -> None:
        app.body_write(Text(app.runner.kv_status(arg), style="yellow"))
