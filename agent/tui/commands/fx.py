from rich.text import Text

from ..fx import FxBar
from .base import Command


class FxCommand(Command):
    name = "/fx"
    summary = "toggle / pin the ambient fx bar"
    usage = "[on|off|auto|<name>]"
    subcommands = (("list", "show available effects"), ("auto", "react to agent state"))

    def run(self, app, arg: str) -> None:
        arg = arg.strip().lower()
        fx = app.query_one("#fx")
        if arg in ("", "toggle"):
            fx.display = not fx.display
            msg = f"fx {'on' if fx.display else 'off'}"
        elif arg == "on":
            fx.display = True
            msg = "fx on"
        elif arg == "off":
            fx.display = False
            msg = "fx off"
        elif arg in ("auto", "reset"):
            fx._pin = None
            fx.display = True
            msg = "fx auto (reacts to state)"
        elif arg in ("list", "?"):
            msg = "fx: " + ", ".join(FxBar.EFFECTS) + " · auto · on · off"
        elif arg in FxBar.EFFECTS:
            fx._pin = arg
            fx.display = True
            msg = f"fx pinned: {arg}  (/fx auto to unpin)"
        else:
            msg = f"unknown fx {arg!r} — try /fx list"
        app.body_write(Text(msg, style="yellow"))
