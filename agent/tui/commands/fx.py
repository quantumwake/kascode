"""/fx — control the ambient fx bar: flip through effects live, set speed, pin a
named effect, toggle visibility, or let it react to the agent's state."""

from rich.text import Text

from ..fx import FxBar
from .base import Command


class FxCommand(Command):
    name = "/fx"
    summary = "control the ambient fx bar (browse, speed, pin, on/off)"
    usage = "[browse|on|off|auto|speed <x>|<name>|list]"
    subcommands = (
        ("browse", "flip through effects live — Tab/Space next, Enter keep, Esc cancel"),
        ("speed", "animation speed — slow|normal|fast|turbo|0.1-5.0"),
        ("list", "show every effect name"),
        ("auto", "react to the agent's state (unpin)"),
    )

    def run(self, app, arg: str) -> None:
        arg = arg.strip().lower()
        fx = app.query_one("#fx")
        verb, _, rest = arg.partition(" ")

        if arg in ("", "browse", "flip"):
            fx.display = True
            app.fx_browse_start()  # interactive: Tab/Space flips from here
            return
        if arg == "on":
            fx.display = True
            msg = "fx on"
        elif arg == "off":
            fx.display = False
            msg = "fx off"
        elif arg == "toggle":
            fx.display = not fx.display
            msg = f"fx {'on' if fx.display else 'off'}"
        elif arg in ("auto", "reset"):
            fx._pin = None
            fx.display = True
            msg = "fx auto (reacts to agent state)"
        elif arg == "status":
            msg = fx.status()
        elif verb == "speed":
            msg = fx.set_speed(rest)
        elif arg in ("list", "effects"):
            msg = "fx effects: " + ", ".join(FxBar.EFFECTS) + "  ·  /fx browse to flip them live"
        elif arg in FxBar.EFFECTS:
            fx._pin = arg
            fx.display = True
            msg = f"fx pinned: {arg}  (/fx auto to unpin)"
        else:
            msg = f"unknown fx {arg!r} — try /fx browse, /fx list, /fx speed <x>, /fx auto"
        app.body_write(Text(msg, style="yellow"))
