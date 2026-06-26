"""Textual TUI for interactive agent sessions.

Three panels:
  - work view  — streamed thinking (dim), text, tool calls/results
  - status bar — model, yolo, live server phase/tok-s (GET /v1/stats), queued steers
  - input      — always live: starts a turn when idle, queues steering
                 messages while the agent works (injected at the next tool
                 boundary), answers confirmations (y / N / a=always)
"""

import json
import pathlib
import queue
import threading

import anthropic
import httpx

try:
    import psutil  # optional ('stats' extra): CPU/RAM/disk/net for the /stats panel
except ImportError:
    psutil = None
from rich.rule import Rule
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.suggester import SuggestFromList
from textual.theme import Theme
from textual.widgets import Input, RichLog, Static

from agent import main as core

from .commands import CommandHandler, command_completions
from .fx import FxBar
from .io import TuiIO
from .loops import WorkerLoops
from .stats import StatsPanel
from .viz import VizModes
from .widgets import Composer, PasteInput, SelectableRichLog

PLACEHOLDER = "task or steering · / for commands (Tab completes, /help) · exit"


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


# Inline ghost suggestions + Tab-complete candidates, generated from the command
# registry (names + subcommands) so they never drift from the actual commands.
COMMANDS = command_completions()


class AgentApp(CommandHandler, StatsPanel, WorkerLoops, App):
    """The TUI composition root. It owns the shared state (set in __init__) and
    the widget tree (compose/on_mount), and inherits its behaviour from three
    mixins so this file stays small: CommandHandler (on_input_submitted +
    /command handlers), StatsPanel (the /stats line + status bar), and
    WorkerLoops (the agent + status worker threads). The mixins reference `self.*`
    state defined here; method lookup resolves across the MRO above. The agent
    thread talks back to this UI through TuiIO (the AgentIO port) via
    call_from_thread — never by touching widgets directly off-thread.
    """

    # Chrome colours come from the active Textual theme (see SCREEN_THEMES /
    # on_mount), so `/theme` reskins the WHOLE screen, not just the fx bar.
    CSS = """
    Screen { background: $background; color: $foreground; }
    #topstats {
        dock: top; height: 1; background: $surface;
        color: $foreground; padding: 0 1; display: none;
    }
    #body { height: 1fr; padding: 0 1; background: $background; color: $foreground; }
    #status { height: 1; background: $surface; color: $accent; padding: 0 1; }
    #fx { height: 1; background: $background; color: $foreground; padding: 0 1; }
    Input { dock: bottom; background: $surface; color: $foreground; border: none; }
    Input:focus { border: none; }
    """
    # Whole-screen palettes: background / surface (status+input) / foreground
    # (text) / accent (status line), hand-tuned for contrast. Names match
    # FxBar.THEMES so `/theme <name>` recolours chrome AND the fx bar together.
    # "amber" is the default (the original retro amber-CRT look).
    SCREEN_THEMES = {
        "amber": {"bg": "#0a0500", "surface": "#1a0e00", "fg": "#ffb000", "accent": "#ff8c00"},
        "matrix": {"bg": "#001400", "surface": "#002a00", "fg": "#39e85a", "accent": "#1aa82a"},
        "ice": {"bg": "#04141f", "surface": "#0a2a4a", "fg": "#a8e8ff", "accent": "#4ec3f0"},
        "fire": {"bg": "#140600", "surface": "#2a0e00", "fg": "#ffae00", "accent": "#ff5e00"},
        "neon": {"bg": "#0a0014", "surface": "#160a28", "fg": "#00f5d4", "accent": "#ff2d95"},
        "synthwave": {"bg": "#0d0221", "surface": "#1a0a3a", "fg": "#ffbe0b", "accent": "#ff006e"},
        "rainbow": {"bg": "#0a0a0f", "surface": "#16161f", "fg": "#f5f5f5", "accent": "#ff8c00"},
        "purple": {"bg": "#0d0420", "surface": "#1a0a3a", "fg": "#d4b0ff", "accent": "#a05cf0"},
        "mono": {"bg": "#0a0a0a", "surface": "#1c1c1c", "fg": "#e8e8e8", "accent": "#888888"},
    }
    BINDINGS = [
        # ctrl+c copies the mouse selection when one exists, quits otherwise
        Binding("ctrl+c", "copy_or_quit", "copy/quit", priority=True),
        Binding("ctrl+q", "quit", "quit", priority=True),
        Binding("escape", "interrupt", "interrupt response", priority=True),
        Binding("ctrl+p", "pause", "pause + save + exit", priority=True),
        Binding("ctrl+o", "compose", "compose / expand", priority=True),
    ]

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        base_url: str,
        workdir,
        yolo: bool,
        max_tokens: int = 16384,
        compact_at: int = 30000,
        store=None,
        messages: list | None = None,
        checkpoint: bool = False,
        net: bool = False,
        rag: bool = False,
        context_limit: int | None = None,
        sandbox: bool = False,
        art: bool = False,
        theme: str = "amber",
        mdui: str = "off",  # off | md | rules | all  (experimental markdown UI)
        mouse_select: bool = True,
    ):
        super().__init__()
        self._initial_theme = (theme or "amber").lower()
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.compact_at = compact_at
        self.base_url = base_url
        self.messages = messages if messages is not None else []
        self.workdir = workdir
        self.io = TuiIO(self)
        self.runner = core.ToolRunner(
            workdir,
            yolo=yolo,
            io=self.io,
            checkpoint=checkpoint,
            net=net,
            rag=rag,
            context_limit=context_limit,
            sandbox=sandbox,
            compact_at=compact_at,
            art=art,
        )
        self.store = store or core.SessionStore(workdir)
        self.msg_q: queue.Queue[str | None] = queue.Queue()
        self.busy = False
        self.fx_mode = "idle"  # current state, drives the ambient FxBar animation
        self.fx_stats: dict = {}  # live tps/processed/total for data-driven fx
        self.tok_in = 0  # cumulative session prompt tokens (for /stats)
        self.tok_out = 0  # cumulative session generated tokens
        self.tok_cache_read = 0  # cumulative cache-read (reused prompt) tokens
        self.tok_cache_create = 0  # cumulative cache-creation tokens
        self.stats_on = False  # /stats panel visible
        self._io_prev: tuple | None = None  # (disk_bytes, net_bytes, t) for IO rates
        self.confirming = False
        self.turns = 0
        self._alive = True
        self._pastes: list[str] = []  # staged multiline pastes, sent with next message
        self._completions = COMMANDS  # Tab-complete candidates (see PasteInput)
        self._fx_browsing = False  # /fx browse: Tab/Space flips effects live
        self.viz = VizModes()  # /viz: per-token confidence/topk/entropy overlays
        self.subagents: list = []  # SubagentIO registry (this session)
        # --- markdown UI (MDUI): GATED, default OFF (known-good plain rendering).
        # An earlier rich-output redesign corrupted the RichLog layout in real
        # terminals; it's gated (--mdui off|md|rules|all) to isolate the culprit.
        #   md    -> render answers as Markdown   rules -> you/kas turn separators
        self._mdui_md = mdui in ("md", "all")
        self._mdui_rule = mdui in ("rules", "all")
        self._mouse_select = mouse_select  # --no-mouse-select disables selection
        # set on user submit; TuiIO writes the "kas" rule before the first agent
        # output (only when rules are enabled).
        self._agent_header_pending = False

    def compose(self) -> ComposeResult:
        yield Static("", id="topstats")  # /stats panel, docked top (hidden by default)
        # Mouse text-selection on by default (SelectableRichLog); --no-mouse-select
        # swaps in a plain RichLog (a suspect in the rich-output regression).
        body_cls = SelectableRichLog if self._mouse_select else RichLog
        yield body_cls(id="body", wrap=True, markup=False, highlight=False, auto_scroll=True)
        yield Static("", id="status")
        yield FxBar()
        yield PasteInput(
            placeholder=PLACEHOLDER,
            id="input",
            suggester=SuggestFromList(COMMANDS, case_sensitive=False),
        )

    def stage_paste(self, text: str) -> None:
        """Hold multiline text as a draft; it attaches to the next submitted
        message. Reopen/edit it in the Composer with Ctrl+O."""
        self._pastes.append(text)
        lines, chars = text.count("\n") + 1, len(text)
        self.body_write(
            Text(
                f"[staged draft · {lines} lines · {chars} chars — Ctrl+O to edit, "
                "or type an instruction (or just Enter) to send]",
                style="magenta",
            )
        )

    def spill_paste_to_file(self, text: str) -> None:
        """Pasting a big/multiline blob into a one-line input is awkward (and breaks
        outright if the terminal has no bracketed-paste). Instead, write the paste
        to a temp file under .agent/pastes/ and drop a compact reference inline, so
        the line reads e.g. `do X with this [pasted content @ .agent/pastes/ab12.txt]`
        and the agent reads the file. .agent is gitignored, so nothing leaks."""
        import hashlib

        ext = "json" if text.lstrip()[:1] in "{[" and _is_json(text) else "txt"
        digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:8]
        d = pathlib.Path(self.workdir) / ".agent" / "pastes"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{digest}.{ext}"
        try:
            path.write_text(text)
            rel = path.relative_to(self.workdir)
        except OSError as exc:
            self.body_write(Text(f"[paste spill failed: {exc}]", style="red"))
            return
        ref = f"[pasted content @ {rel}]"
        inp = self.query_one(Input)
        pos = inp.cursor_position
        inp.value = f"{inp.value[:pos]}{ref}{inp.value[pos:]}"
        inp.cursor_position = pos + len(ref)
        lines = text.count("\n") + 1
        self.body_write(
            Text(
                f"[pasted {lines} lines · {len(text)} chars → {rel} · referenced inline]",
                style="magenta",
            )
        )

    def action_compose(self, extra: str = "") -> None:
        """Open the Composer over the current input + staged draft(s) (+ `extra`),
        so long / multiline text is fully visible and editable. Bound to Ctrl+O;
        also called with the pasted text on a multiline paste."""
        inp = self.query_one(Input)
        parts = [p for p in (inp.value, *self._pastes, extra) if p]
        inp.value = ""
        self._pastes = []
        self.push_screen(Composer("\n\n".join(parts)), self._composer_result)

    def _composer_result(self, result) -> None:
        """Composer result. Only 'send' acts here; any other close path already
        preserved the text as a draft via Composer.on_unmount."""
        if not result:
            return
        action, text = result
        text = text.strip()
        if action == "send" and text:
            self._submit_message(text)

    # ---- /fx browse: flip through effects live on the real bar ----

    def fx_browse_start(self) -> None:
        fx = self.query_one("#fx")
        self._fx_browsing = True
        self._fx_browse_prev = fx._pin  # restore on cancel
        fx.display = True
        name = fx.cycle(0)  # pin the current effect to start
        self.query_one(
            Input
        ).placeholder = (
            f"fx browse: {name}  ·  Tab/Space next · Shift+Tab prev · Enter keep · Esc cancel"
        )
        self.body_write(
            Text(
                f"fx browse: {name}  —  Tab/Space next · Shift+Tab prev · Enter keep · Esc cancel",
                style="yellow",
            )
        )

    def fx_browse_step(self, delta: int) -> None:
        if not self._fx_browsing:
            return
        name = self.query_one("#fx").cycle(delta)
        self.query_one(
            Input
        ).placeholder = f"fx browse: {name}  ·  Tab/Space next · Enter keep · Esc cancel"

    def fx_browse_end(self, keep: bool) -> None:
        if not self._fx_browsing:
            return
        fx = self.query_one("#fx")
        if not keep:
            fx._pin = self._fx_browse_prev  # restore what was pinned before
        self._fx_browsing = False
        self.query_one(Input).placeholder = PLACEHOLDER
        kept = fx._pin or "auto"
        self.body_write(Text(f"fx: {kept}{'' if keep else ' (cancelled)'}", style="yellow"))

    def action_interrupt(self) -> None:
        if self._fx_browsing:  # Esc cancels fx browse before anything else
            self.fx_browse_end(keep=False)
            return
        # Escape is a priority binding, so it fires app-wide — even over a modal,
        # whose own escape→dismiss would otherwise be shadowed. So if a modal is
        # open (subagent view, model picker), close THAT first instead of
        # interrupting the response running underneath.
        if len(self.screen_stack) > 1:
            self.screen.dismiss()
            return
        if self.busy:
            self.io.abort.set()
            # Aborting the stream only takes effect once tokens flow — a long
            # prefill emits none, so also tell the server to drop the job NOW.
            self._cancel_server()
            self.body_write(Text("[interrupting…]", style="yellow"))
        else:
            self.body_write(Text("[nothing to interrupt]", style="dim"))

    def _cancel_server(self) -> None:
        """Fire POST /v1/cancel off-thread so Escape stays instant."""
        base = self.base_url.rstrip("/")

        def post() -> None:
            try:
                httpx.post(base + "/v1/cancel", timeout=3)
            except Exception:
                pass

        threading.Thread(target=post, daemon=True).start()

    def action_pause(self) -> None:
        """Stop at a safe boundary, save (marked paused), exit. Resume continues."""
        self.body_write(Text("[pausing — saving session & exiting…]", style="yellow"))
        self.io.pause.set()
        if self.busy:
            self.io.abort.set()  # stop generation; _agent_loop saves+exits when it returns
        else:
            self._save_paused()
            self.exit()

    def _save_paused(self) -> None:
        try:
            self.store.save_transcript(self.messages, self.model, paused=True)
            self.body_write(
                Text(f"[paused · resume: kas --resume {self.store.id}]", style="#ffb000")
            )
        except Exception as exc:
            self.body_write(Text(f"[pause save failed] {exc}", style="red"))

    def action_copy_or_quit(self) -> None:
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.screen.clear_selection()
            self.body_write(Text(f"[copied {len(text)} chars]", style="dim"))
        else:
            self.exit()

    def on_mount(self) -> None:
        self.title = "K.A.S"
        self.sub_title = "Kasra's Agentic Shell"
        for name, c in self.SCREEN_THEMES.items():
            self.register_theme(
                Theme(
                    name=name,
                    primary=c["accent"],
                    secondary=c["accent"],
                    accent=c["accent"],
                    foreground=c["fg"],
                    background=c["bg"],
                    surface=c["surface"],
                    panel=c["surface"],
                    dark=True,
                )
            )
        want = self._initial_theme if self._initial_theme in self.SCREEN_THEMES else "amber"
        self.theme = want
        # An explicit non-default theme pins the fx bar to match; plain "amber"
        # keeps the bar's lively colour rotation (the default look).
        if want != "amber":
            self.query_one("#fx").set_theme(want)
        self.query_one(Input).focus()
        from scripts.banner import tui_lines

        for text, style in tui_lines(model=self.model, extra=f"workdir {self.workdir}"):
            self.body_write(Text(text, style=style))
        self.body_write(
            Text(
                "type a task; keep typing while it works to steer it · "
                "y/N/a at confirmations · Ctrl+O to compose/paste multiline · / for commands",
                style="#cc7000",
            )
        )
        if self.messages:
            self.turns = len(self.messages)
            self.body_write(
                Text(
                    f"resumed session {self.store.id} ({len(self.messages)} messages):",
                    style="green",
                )
            )
            self._replay_transcript()  # re-render the full history into the work view
            self.body_write(Text("— end of restored history —\n", style="dim"))
        threading.Thread(target=self._agent_loop, daemon=True).start()
        # auto-continue a session that was mid-task / paused when saved
        if self.messages and core.SessionStore.should_continue(
            self.messages, getattr(self.store, "was_paused", False)
        ):
            self.body_write(Text("[resuming the task automatically…]", style="green"))
            self.msg_q.put("\x00continue")
        threading.Thread(target=self._status_loop, daemon=True).start()

    def on_unmount(self) -> None:
        self._alive = False
        self.msg_q.put(None)
        if self.runner.session is not None:
            self.runner.session.kill()

    # ---- UI-thread helpers ----

    def _replay_transcript(self) -> None:
        """Re-render the restored conversation into the work view on --resume, so
        the user sees the full prior text (not a blank panel). Mirrors the live
        plain rendering; restored blocks are JSON dicts. Best-effort per block."""
        for m in self.messages:
            role = m.get("role")
            content = m.get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if role == "user" and btype == "tool_result":
                    out = b.get("content", "")
                    if isinstance(out, list):  # content may itself be a list of blocks
                        out = "".join(x.get("text", "") for x in out if isinstance(x, dict))
                    err = bool(b.get("is_error"))
                    mark, style = ("✗", "red") if err else ("✓", "green")
                    self.body_write(Text(f"  {mark} {str(out)[:300]}", style=style))
                elif role == "user" and btype == "text":
                    self.body_write(Text(f"\nyou> {b.get('text', '')}", style="bold"))
                elif role == "assistant" and btype == "thinking":
                    self.body_write(Text(b.get("thinking", ""), style="dim italic"))
                elif role == "assistant" and btype == "text":
                    self.body_write(Text(b.get("text", "")))
                elif role == "assistant" and btype == "tool_use":
                    args = json.dumps(b.get("input", {}), ensure_ascii=False)[:200]
                    self.body_write(Text(f"→ {b.get('name', '')}({args})", style="bold cyan"))

    def body_write(self, renderable) -> None:
        log = self.query_one("#body", RichLog)
        # Sticky tail: follow new output ONLY when already pinned to the bottom.
        # With plain auto_scroll, every write yanked the view back down, so once
        # you scrolled up to read or SELECT earlier output it jumped away — making
        # the main area impossible to select while anything was being written.
        log.write(renderable, scroll_end=log.is_vertical_scroll_end)

    def turn_rule(self, label: str, color: str) -> None:
        """A left-aligned labeled separator between turns (── label ──────).
        Only used when KAS_MDUI_RULES is on (gated; see __init__)."""
        self.body_write(Rule(Text(f" {label} ", style=f"bold {color}"), align="left", style=color))

    def register_subagent(self, sub) -> None:
        self.subagents.append(sub)
        self.body_write(
            Text(
                f"spawned subagent[{sub.n}]: {sub.label}  ·  /subagents to list, "
                f"/subagent {sub.n} to watch",
                style="cyan",
            )
        )

    def refresh_status(self) -> None:
        pass  # status bar repaints on its own 1s tick; hook kept for callers

    def enter_confirm(self, command: str) -> None:
        self.confirming = True
        # A prominent, single-keypress prompt (answered by y/n/a, no Enter).
        self.body_write(Text("─" * 46, style="#ff8c00"))
        self.body_write(Text("run this command?", style="bold #ffb000"))
        self.body_write(Text(f"  $ {command}", style="bold"))
        self.body_write(Text("  [Y]es     [N]o     [A]lways", style="bold #ffb000"))
        self.body_write(Text("  press y / n / a  ·  no Enter needed", style="dim"))
        self.query_one(Input).placeholder = "press  y / n / a"

    def exit_confirm(self) -> None:
        self.confirming = False
        self.query_one(Input).placeholder = PLACEHOLDER

    def action_confirm(self, answer: str) -> None:
        """Resolve the active command-confirmation. Called from PasteInput.on_key
        on a single y/n/a keypress (see widgets.py)."""
        if not self.confirming:
            return
        self.confirming = False  # guard a second keypress from double-answering
        self.body_write(Text(f"  → {answer}", style="dim"))
        self.io.confirm_q.put(answer)  # unblocks the agent thread (TuiIO.confirm)
