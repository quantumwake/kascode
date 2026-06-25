"""/ai-wellbeing — reflective self-assessment, or `chart` to view the history.

/ai-wellbeing          run a fresh assessment (logs to the CSV)
/ai-wellbeing chart    text sparklines of every logged assessment over time
/ai-wellbeing chart here   ...restricted to this workdir
"""

from pathlib import Path

from rich.text import Text

from agent.core.ai_wellbeing import CSV_PATH, chart_lines, read_history

from .base import Command

_CHART_WORDS = {"chart", "history", "trend", "graph", "log", "stats"}


class AiWellbeingCommand(Command):
    name = "/ai-wellbeing"
    summary = "reflective self-assessment; logs scores to a CSV"
    subcommands = (
        ("chart", "text sparklines of past assessments over time"),
        ("chart here", "…restricted to this workdir"),
    )

    def run(self, app, arg: str) -> None:
        parts = arg.strip().lower().split()
        if parts and parts[0] in _CHART_WORDS:
            self._chart(app, here="here" in parts)
            return
        if app.busy:
            app.body_write(Text("[/ai-wellbeing: wait until the agent is idle]", style="yellow"))
        elif not app.messages:
            app.body_write(Text("[ai-wellbeing: no conversation yet to assess]", style="yellow"))
        else:
            app.msg_q.put("\x00ai-wellbeing")

    @staticmethod
    def _chart(app, here: bool) -> None:
        rows = read_history(CSV_PATH)
        if here:
            name = Path(app.workdir).name
            rows = [r for r in rows if r.get("workdir") == name]
        if not rows:
            scope = " here" if here else ""
            app.body_write(
                Text(
                    f"[ai-wellbeing: no history{scope} yet — run /ai-wellbeing to record one]",
                    style="yellow",
                )
            )
            return
        for line, style in chart_lines(rows):
            app.body_write(Text(line, style=style))
