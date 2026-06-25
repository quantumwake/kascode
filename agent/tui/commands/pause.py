from .base import Command


class PauseCommand(Command):
    name = "/pause"
    summary = "save the session and exit; resume later (^P)"

    def run(self, app, arg: str) -> None:
        app.action_pause()
