from .base import Command


class StopCommand(Command):
    name = "/stop"
    summary = "interrupt the running response (same as Esc)"

    def run(self, app, arg: str) -> None:
        app.action_interrupt()
