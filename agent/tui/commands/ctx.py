from rich.text import Text

from .base import Command


class CtxCommand(Command):
    name = "/ctx"
    summary = "show or set the context-token budget"
    usage = "[<n>|max|auto]"
    subcommands = (
        ("max", "cap context to the model's limit"),
        ("auto", "auto-manage the token budget"),
    )

    def run(self, app, arg: str) -> None:
        from agent.core.compaction import ctx_command

        # arg is the raw remainder (e.g. " max"); ctx_command strips it.
        app.body_write(Text(ctx_command(app.runner, arg), style="yellow"))
