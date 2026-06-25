from rich.text import Text

from ..widgets import SubagentView
from .base import Command


class SubagentCommand(Command):
    name = "/subagent"
    summary = "watch a subagent's transcript (/subagents lists them)"
    usage = "<n>"

    def match(self, text: str) -> str | None:
        # historical prefix: matches "/subagent", "/subagents", "/subagent 2"
        return text[len(self.name) :] if text.startswith(self.name) else None

    def completions(self) -> list[str]:
        return ["/subagents", "/subagent"]  # plural lists, singular drills in

    def run(self, app, arg: str) -> None:
        rest = arg.lstrip()
        # /subagents (list)  ·  /subagent N (drill in)
        if rest.lstrip("s").strip() == "" and not rest[:1].isdigit():
            if not app.subagents:
                app.body_write(Text("no subagents spawned this session", style="yellow"))
            else:
                app.body_write(Text("subagents:", style="yellow"))
                for s in app.subagents:
                    app.body_write(Text(f"  [{s.n}] {s.status:<7} {s.label}", style="yellow"))
                app.body_write(Text("open one with /subagent <n>", style="yellow"))
        else:
            sub = rest.lstrip("s").strip()
            match = next((s for s in app.subagents if str(s.n) == sub), None)
            if match:
                app.push_screen(SubagentView(match))
            else:
                app.body_write(Text(f"no subagent {sub!r} — /subagents to list", style="red"))
