from rich.text import Text

from .base import Command


class SandboxCommand(Command):
    name = "/sandbox"
    summary = "explain sandbox status (gated; microVM extension)"

    def run(self, app, arg: str) -> None:
        # Sandboxing is disabled and gated: a file-tools-only jail let bash escape,
        # so it was removed rather than imply a containment it can't enforce. Real
        # isolation is a future microVM-isolation extension.
        app.body_write(
            Text(
                "sandbox: OFF (gated). Real isolation is a future microVM extension — "
                "the old file-tools-only jail was removed because bash escaped it. "
                "Tools currently run with your full permissions; review what you run.",
                style="#ff8c00",
            )
        )
