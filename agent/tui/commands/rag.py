from rich.text import Text

from .base import Command


class RagCommand(Command):
    name = "/rag"
    summary = "local code / docs / memory retrieval"
    usage = "[enable|disable]"
    subcommands = (("enable", "turn recall on"), ("disable", "turn recall off"))

    def match(self, text: str) -> str | None:
        # historical: any "/rag..." prefix (so "/ragfoo" reaches the usage hint)
        return text[len(self.name) :] if text.startswith(self.name) else None

    def run(self, app, arg: str) -> None:
        arg = arg.strip().lower()
        if arg in ("enable", "on"):
            app.runner.rag = True
        elif arg in ("disable", "off"):
            app.runner.rag = False
        elif arg:
            app.body_write(Text("usage: /rag [enable|disable]", style="yellow"))
            return
        app.body_write(
            Text(
                "recall ENABLED — local code/docs/memory search available"
                if app.runner.rag
                else "recall DISABLED",
                style="yellow",
            )
        )
