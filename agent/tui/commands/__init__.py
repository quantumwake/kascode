"""TUI slash commands: a registry of one-class-per-command handlers plus the
input router that dispatches to them.

CommandHandler is mixed into AgentApp. on_input_submitted routes every submitted
line: confirmations, /commands (via REGISTRY), exit, and — when busy — steering
vs (when idle) a new turn. Adding a command = a new module in this package + one
line in REGISTRY; the dispatcher and AgentApp don't change.
"""

from rich.text import Text
from textual.widgets import Input

from .ai_wellbeing import AiWellbeingCommand
from .art import ArtCommand
from .compact import CompactCommand
from .ctx import CtxCommand
from .fx import FxCommand
from .help import HelpCommand
from .kv import KvCommand
from .memory import MemoryCommand, RagCommand
from .model import ModelCommand
from .pause import PauseCommand
from .sandbox import SandboxCommand
from .self_skill import SelfSkillCommand
from .spec import SpecCommand
from .stats import StatsCommand
from .status import StatusCommand
from .stop import StopCommand
from .subagent import SubagentCommand
from .theme import ThemeCommand
from .viz import VizCommand
from .yolo import YoloCommand

# Ordered: prefix-matching commands (/model, /rag, /subagent) keep their relative
# order so none shadows another — this mirrors the historical dispatch order.
REGISTRY = [
    StopCommand(),
    PauseCommand(),
    ModelCommand(),
    CompactCommand(),
    SelfSkillCommand(),
    AiWellbeingCommand(),
    SpecCommand(),
    YoloCommand(),
    SubagentCommand(),
    FxCommand(),
    ThemeCommand(),
    VizCommand(),
    MemoryCommand(),
    RagCommand(),  # deprecated alias — keep after /memory so it doesn't shadow it
    StatsCommand(),
    CtxCommand(),
    KvCommand(),
    ArtCommand(),
    SandboxCommand(),
    StatusCommand(),
]
_HELP = HelpCommand()

__all__ = ["CommandHandler", "REGISTRY", "command_completions"]


def command_completions() -> list[str]:
    """Every Tab-complete candidate: each command's name + `/name <subcommand>`
    (and any aliases), plus `exit`. Feeds both the inline suggester and Tab."""
    out: list[str] = []
    for cmd in REGISTRY:
        out.extend(cmd.completions())
    out.append("exit")
    return out


class CommandHandler:
    """Mixin on AgentApp: the input router + /command dispatch."""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if getattr(self, "_fx_browsing", False):  # Enter keeps the browsed effect
            self.fx_browse_end(keep=True)
            return
        # confirmations and slash-commands act on the typed line only; staged
        # pastes (if any) stay staged for the next real message.
        if self.confirming:
            self.io.confirm_q.put(text)
            return
        if not text and not self._pastes:
            return
        if text in ("exit", "quit"):
            self.exit()
            return
        if text.startswith("/") and not self._pastes:
            self._dispatch_command(text)
            return
        # attach staged multiline paste(s): typed instruction first, blob after
        if self._pastes:
            blob = "\n\n".join(self._pastes)
            self._pastes = []
            text = f"{text}\n\n{blob}" if text else blob
        self._submit_message(text)

    def _submit_message(self, text: str) -> None:
        """Send a finished user message: steer it in if the agent is busy, else
        start a new turn. Shared by the input router and the Composer."""
        if self.busy:
            self.io.steer_q.put(text)
            self.body_write(
                Text("[queued steering — applies at the next tool boundary]", style="magenta")
            )
            return
        preview = text.splitlines()[0][:80] + (" …" if "\n" in text or len(text) > 80 else "")
        if getattr(self, "_mdui_rule", False):  # gated; default OFF
            self.turn_rule("you", "#3fb950")
            self.body_write(Text(preview))
            self._agent_header_pending = True
        else:
            self.body_write(Text(f"\nyou> {preview}", style="bold"))
        self.msg_q.put(text)

    def _dispatch_command(self, text: str) -> None:
        """Route a /slash command to the first registry entry that matches; the
        help line is the fallback for an unknown command."""
        for cmd in REGISTRY:
            arg = cmd.match(text)
            if arg is not None:
                cmd.run(self, arg)
                return
        _HELP.run(self, "")
