from rich.text import Text

from .base import Command


class HelpCommand(Command):
    """The fallback for an unrecognised /command — never matched directly. Renders
    the menu from the registry, so every command (and its subcommands) lists its
    own summary; nothing to keep in sync by hand."""

    name = "/help"
    summary = "list commands and what they do"

    def run(self, app, arg: str) -> None:
        from . import REGISTRY

        rows = [
            (c.name + (f" {c.usage}" if c.usage else ""), c.summary, c.subcommands)
            for c in REGISTRY
        ]
        rows.append(("exit", "quit kas", ()))
        width = max(len(head) for head, _, _ in rows)
        app.body_write(Text("commands  ·  Tab to autocomplete", style="bold #ffb000"))
        for head, summary, subs in rows:
            app.body_write(Text(f"  {head.ljust(width)}   {summary}", style="yellow"))
            for sub, desc in subs:
                app.body_write(Text(f"  {' ' * width}     {sub} — {desc}", style="dim"))
        app.body_write(
            Text(
                "  keys: Tab complete · Esc stop · ^P pause · ^O compose/paste · ^C copy/quit",
                style="dim",
            )
        )
