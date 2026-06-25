from rich.text import Text

from ..widgets import SpecWizard
from .base import Command


class SpecCommand(Command):
    name = "/spec"
    summary = "guided spec wizard → SPEC.md → autonomous build"

    def run(self, app, arg: str) -> None:
        if app.busy:
            app.body_write(Text("[/spec: wait until the agent is idle]", style="yellow"))
            return
        from agent.core.spec import spec_seed

        def chosen(kind: str | None) -> None:
            # Picked a project kind -> seed a normal turn with SPEC MODE; the agent
            # asks follow-ups, writes SPEC.md, and (after approval) builds it.
            if not kind:
                return
            app.body_write(
                Text(f"── spec: {kind} — answer the agent's questions ──", style="green")
            )
            app.msg_q.put(spec_seed(kind))

        app.push_screen(SpecWizard(), chosen)
