from rich.text import Text

from .base import Command


class CompactCommand(Command):
    name = "/compact"
    summary = "summarise the conversation to reclaim context"

    def run(self, app, arg: str) -> None:
        if app.busy:
            app.body_write(Text("[/compact: wait until the agent is idle]", style="yellow"))
        elif not app.messages:
            app.body_write(Text("[nothing to compact yet]", style="yellow"))
        else:
            app.msg_q.put("\x00compact")
