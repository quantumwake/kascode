from rich.text import Text

from .base import Command


class StatsCommand(Command):
    name = "/stats"
    summary = "toggle the live system / throughput panel"

    def run(self, app, arg: str) -> None:
        panel = app.query_one("#topstats")
        panel.display = not panel.display
        app.stats_on = panel.display
        app.body_write(Text(f"stats panel {'on' if panel.display else 'off'}", style="yellow"))
