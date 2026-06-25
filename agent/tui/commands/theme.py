from rich.text import Text

from .base import Command


class ThemeCommand(Command):
    name = "/theme"
    summary = "reskin the whole UI (amber, matrix, ice, …)"
    usage = "<name>"

    def run(self, app, arg: str) -> None:
        arg = arg.strip().lower()
        fx = app.query_one("#fx")
        fx.display = True
        # reskin the whole screen too: a named theme repaints chrome; auto falls
        # back to the default amber chrome (fx then rotates colours).
        if arg in app.SCREEN_THEMES:
            app.theme = arg
        elif arg in ("auto", "off", "none"):
            app.theme = "amber"
        app.body_write(Text(fx.set_theme(arg), style="yellow"))
