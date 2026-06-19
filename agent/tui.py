"""Textual TUI for interactive agent sessions.

Three panels:
  - work view  — streamed thinking (dim), text, tool calls/results
  - status bar — model, yolo, live server phase/tok-s (GET /v1/stats), queued steers
  - input      — always live: starts a turn when idle, queues steering
                 messages while the agent works (injected at the next tool
                 boundary), answers confirmations (y / N / a=always)
"""

import json
import math
import queue
import random
import threading
import time

import anthropic
import httpx
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from agent import main as core
from scripts.select_model import downloaded_models

PLACEHOLDER = "task or steering · / for commands · exit"
COMMANDS = ["/yolo", "/rag", "/rag enable", "/rag disable", "/subagents", "/status",
            "/ctx", "/ctx max", "/ctx auto", "/kv", "/art", "/compact", "/fx", "/stop", "/pause", "/model", "exit"]


class ModelSelect(ModalScreen):
    """Arrow-key/click model picker (↑↓ + Enter, Esc to cancel)."""

    CSS = """
    ModelSelect { align: center middle; }
    #ms-box { width: 80%; max-width: 90; height: auto; max-height: 80%;
              background: #1a0e00; border: round #ff9d00; padding: 1 2; }
    #ms-title { color: #ffb000; text-style: bold; padding-bottom: 1; }
    ModelSelect OptionList { background: #1a0e00; color: #ffb000; border: none; }
    ModelSelect OptionList > .option-list--option-highlighted {
        background: #ff9d00; color: #1a0e00; text-style: bold; }
    """
    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def __init__(self, models: list[str], current: str) -> None:
        super().__init__()
        self._models = models
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="ms-box"):
            yield Static("select a model  ·  ↑↓ + Enter  ·  Esc to cancel", id="ms-title")
            yield OptionList(
                *[Option(("● " if m == self._current else "  ") + m, id=m) for m in self._models]
            )

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SubagentView(ModalScreen):
    """Scrollable read-only view of one subagent's captured transcript."""

    CSS = """
    SubagentView { align: center middle; }
    #sv-box { width: 90%; height: 85%; background: #0a0500; border: round #ff9d00; padding: 1 2; }
    #sv-title { color: #ffb000; text-style: bold; padding-bottom: 1; }
    SubagentView RichLog { background: #0a0500; color: #cc7000; }
    """
    BINDINGS = [Binding("escape", "dismiss", "close")]

    def __init__(self, sub) -> None:
        super().__init__()
        self._sub = sub

    def compose(self) -> ComposeResult:
        with Vertical(id="sv-box"):
            yield Static(f"subagent[{self._sub.n}] · {self._sub.status} · {self._sub.label}  (Esc to close)",
                         id="sv-title")
            log = RichLog(wrap=True, markup=False, highlight=False)
            yield log

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        for line in (self._sub.buffer or ["(no captured output)"]):
            log.write(Text(line, style="#cc7000"))

    def action_dismiss(self) -> None:
        self.dismiss(None)


class FxBar(Static):
    """A one-row ambient amber-CRT animation strip — purely for fun.

    Cycles through a few retro effects on its own (twinkle / equalizer wave /
    comet sweep). Toggle with /fx. Updates a single line, so it's cheap.
    """

    GLYPHS = "·✦*°⋆+•∙"
    SHADES = ["#3a2000", "#7a4500", "#b86800", "#ffb000", "#ffd470"]
    BARS = " ▁▂▃▄▅▆▇█"
    EFFECTS = ("twinkle", "wave", "comet")

    def __init__(self) -> None:
        super().__init__("", id="fx")
        self._t = 0
        self._effect = "twinkle"
        self._cells: list[float] = []
        self._glyphs: list[str] = []

    def on_mount(self) -> None:
        self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        w = max(0, self.size.width)
        if w == 0:
            return
        self._t += 1
        if self._t % 70 == 0:  # switch effect now and then, for variety
            self._effect = random.choice(self.EFFECTS)
        render = {"twinkle": self._twinkle, "wave": self._wave, "comet": self._comet}[self._effect]
        self.update(render(w))

    def _twinkle(self, w: int) -> Text:
        if len(self._cells) != w:
            self._cells = [0.0] * w
            self._glyphs = [" "] * w
        for i in range(w):
            self._cells[i] *= 0.82  # fade
        for _ in range(max(1, w // 50)):  # spawn a few new sparks
            i = random.randrange(w)
            self._cells[i] = 1.0
            self._glyphs[i] = random.choice(self.GLYPHS)
        t = Text()
        for i in range(w):
            v = self._cells[i]
            if v < 0.12:
                t.append(" ")
            else:
                t.append(self._glyphs[i], style=self.SHADES[min(4, int(v * 5))])
        return t

    def _wave(self, w: int) -> Text:
        t = Text()
        for col in range(w):
            y = math.sin(col * 0.25 + self._t * 0.2) * 0.5 + math.sin(col * 0.07 - self._t * 0.13) * 0.5
            idx = max(0, min(len(self.BARS) - 1, int((y + 1) / 2 * (len(self.BARS) - 1))))
            t.append(self.BARS[idx], style=self.SHADES[1 + (idx * 3) // len(self.BARS)])
        return t

    def _comet(self, w: int) -> Text:
        pos = (self._t * 2) % (w + 24) - 12
        t = Text()
        for i in range(w):
            d = abs(i - pos)
            if d > 6:
                t.append(" ")
            else:
                t.append("═" if d <= 2 else "─", style=self.SHADES[max(0, 4 - d)])
        return t


class PasteInput(Input):
    """Single-line Input that doesn't shred multiline paste.

    Stock Input._on_paste keeps only splitlines()[0]. We intercept a multiline
    paste and hand the full text to the app to stage (attached to the next
    message) instead of flattening it into the one-line field.
    """

    def _on_paste(self, event) -> None:
        if event.text and "\n" in event.text:
            self.app.stage_paste(event.text)
            event.stop()
            return
        super()._on_paste(event)


class SelectableRichLog(RichLog):
    """RichLog with mouse text selection.

    Textual's selection machinery needs the widget to map a Selection to
    text; stock RichLog doesn't implement it. Its internal `lines` are the
    rendered visual lines (Strips), which is exactly the coordinate space
    selections are made in.
    """

    ALLOW_SELECT = True

    def get_selection(self, selection) -> tuple[str, str] | None:
        text = "\n".join(strip.text for strip in self.lines)
        return selection.extract(text), "\n"


class TuiIO:
    """core.agent_turn IO interface, marshalling from the agent thread to the UI."""

    def __init__(self, app: "AgentApp") -> None:
        self.app = app
        self.steer_q: "queue.Queue[str]" = queue.Queue()
        self.confirm_q: "queue.Queue[str]" = queue.Queue()
        self.abort = threading.Event()
        self.pause = threading.Event()
        self.last_decode_tps: float = 0.0
        self._line = ""
        self._kind = "text"
        self._t0 = 0.0
        self._ttft: float | None = None

    def _ui(self, fn, *args) -> None:
        try:
            self.app.call_from_thread(fn, *args)
        except Exception:
            pass  # app shutting down

    def _write(self, text: str, style: str = "") -> None:
        self._ui(self.app.body_write, Text(text, style=style))

    def _flush_line(self) -> None:
        if self._line:
            self._write(self._line, "dim italic" if self._kind == "thinking" else "")
            self._line = ""

    # ---- interface called by core.agent_turn (agent thread) ----

    def stream_started(self) -> None:
        self._t0, self._ttft = time.time(), None

    def delta(self, kind: str, text: str) -> None:
        if self._ttft is None:
            self._ttft = time.time() - self._t0
        if kind != self._kind:
            self._flush_line()
            self._kind = kind
        self._line += text
        while "\n" in self._line:
            line, self._line = self._line.split("\n", 1)
            self._write(line, "dim italic" if kind == "thinking" else "")

    def stream_finished(self, usage) -> None:
        self._flush_line()
        if usage is not None:
            decode_t = max(0.05, (time.time() - self._t0) - (self._ttft or 0))
            self.last_decode_tps = usage.output_tokens / decode_t
            self._write(
                f"[{usage.input_tokens} in / {usage.output_tokens} out · "
                f"ttft {self._ttft or 0:.1f}s · {self.last_decode_tps:.1f} tok/s · "
                f"total {time.time() - self._t0:.1f}s]",
                "dim",
            )

    def tool_call(self, name: str, args: dict) -> None:
        self._flush_line()
        self._write(f"→ {name}({json.dumps(args, ensure_ascii=False)[:200]})", "bold cyan")

    def tool_result(self, output: str, is_error: bool) -> None:
        preview = output if len(output) < 300 else output[:300] + "..."
        mark, style = ("✗", "red") if is_error else ("✓", "green")
        self._write(f"  {mark} {preview}", style)

    def notice(self, text: str) -> None:
        self._flush_line()
        self._write(text, "yellow")

    def confirm(self, command: str) -> str:
        self._ui(self.app.enter_confirm, command)
        answer = self.confirm_q.get()  # blocks the agent thread, UI stays live
        self._ui(self.app.exit_confirm)
        return answer.strip().lower()

    def drain_steers(self) -> list[str]:
        out: list[str] = []
        while True:
            try:
                out.append(self.steer_q.get_nowait())
            except queue.Empty:
                return out

    def should_abort(self) -> bool:
        return self.abort.is_set()

    def should_pause(self) -> bool:
        return self.pause.is_set()

    def clear_abort(self) -> None:
        self.abort.clear()

    # subagent lifecycle → app registry (for /subagents + drill-in)
    def subagent_started(self, sub) -> None:
        self._ui(self.app.register_subagent, sub)

    def subagent_finished(self, sub, ok: bool) -> None:
        self._ui(self.app.refresh_status)


class AgentApp(App):
    # amber-on-black: retro BBS / amber-CRT
    CSS = """
    Screen { background: #0a0500; color: #ffb000; }
    #body { height: 1fr; padding: 0 1; background: #0a0500; color: #ffb000; }
    #status { height: 1; background: #1a0e00; color: #ff8c00; padding: 0 1; }
    #fx { height: 1; background: #0a0500; color: #ffb000; padding: 0 1; }
    Input { dock: bottom; background: #1a0e00; color: #ffb000; border: none; }
    Input:focus { border: none; }
    """
    BINDINGS = [
        # ctrl+c copies the mouse selection when one exists, quits otherwise
        Binding("ctrl+c", "copy_or_quit", "copy/quit", priority=True),
        Binding("ctrl+q", "quit", "quit", priority=True),
        Binding("escape", "interrupt", "interrupt response", priority=True),
        Binding("ctrl+p", "pause", "pause + save + exit", priority=True),
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
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.compact_at = compact_at
        self.base_url = base_url
        self.messages = messages if messages is not None else []
        self.workdir = workdir
        self.io = TuiIO(self)
        self.runner = core.ToolRunner(
            workdir, yolo=yolo, io=self.io, checkpoint=checkpoint, net=net, rag=rag,
            context_limit=context_limit, sandbox=sandbox, compact_at=compact_at, art=art,
        )
        self.store = store or core.SessionStore(workdir)
        self.msg_q: "queue.Queue[str | None]" = queue.Queue()
        self.busy = False
        self.confirming = False
        self.turns = 0
        self._alive = True
        self._pastes: list[str] = []  # staged multiline pastes, sent with next message
        self.subagents: list = []  # SubagentIO registry (this session)

    def compose(self) -> ComposeResult:
        yield SelectableRichLog(id="body", wrap=True, markup=False, highlight=False, auto_scroll=True)
        yield Static("", id="status")
        yield FxBar()
        yield PasteInput(
            placeholder=PLACEHOLDER,
            id="input",
            suggester=SuggestFromList(COMMANDS, case_sensitive=False),
        )

    def stage_paste(self, text: str) -> None:
        """Hold a multiline paste; it attaches to the next submitted message."""
        self._pastes.append(text)
        lines, chars = text.count("\n") + 1, len(text)
        self.body_write(
            Text(f"[staged paste · {lines} lines · {chars} chars — type an instruction "
                 "(or just Enter) to send]", style="magenta")
        )

    def _handle_model_command(self, arg: str) -> None:
        models = downloaded_models()
        if not models:
            self.body_write(Text("no downloaded models — make download MODEL=…", style="yellow"))
            return
        if not arg:
            # interactive picker
            def chosen(target: str | None) -> None:
                if target and target != self.model:
                    self._switch_model(target)
            self.push_screen(ModelSelect(models, self.model), chosen)
            return
        # direct switch by id or list number
        if arg.isdigit() and 1 <= int(arg) <= len(models):
            target = models[int(arg) - 1]
        elif arg in models:
            target = arg
        else:
            self.body_write(Text(f"unknown model {arg!r} — /model to pick", style="red"))
            return
        if target == self.model:
            self.body_write(Text(f"already serving {target}", style="yellow"))
            return
        self._switch_model(target)

    def _switch_model(self, target: str) -> None:
        self.body_write(Text(f"[switching to {target} — loading…]", style="yellow"))

        def do_swap() -> None:
            try:
                resp = httpx.post(
                    self.base_url.rstrip("/") + "/v1/models/select",
                    json={"model": target}, timeout=900,
                ).json()
                if resp.get("ok"):
                    self.model = resp["model"]
                    note = f"[now serving {resp['model']} (dialect: {resp.get('dialect')})]"
                else:
                    note = f"[swap failed: {resp.get('error', {}).get('message', resp)}]"
            except Exception as exc:
                note = f"[swap failed: {exc}]"
            try:
                self.call_from_thread(self.body_write, Text(note, style="yellow"))
            except Exception:
                pass

        threading.Thread(target=do_swap, daemon=True).start()

    def action_interrupt(self) -> None:
        # Escape is a priority binding, so it fires app-wide — even over a modal,
        # whose own escape→dismiss would otherwise be shadowed. So if a modal is
        # open (subagent view, model picker), close THAT first instead of
        # interrupting the response running underneath.
        if len(self.screen_stack) > 1:
            self.screen.dismiss()
            return
        if self.busy:
            self.io.abort.set()
            self.body_write(Text("[interrupting…]", style="yellow"))
        else:
            self.body_write(Text("[nothing to interrupt]", style="dim"))

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
            self.body_write(Text(f"[paused · resume: kas --resume {self.store.id}]", style="#ffb000"))
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
        self.query_one(Input).focus()
        from scripts.banner import tui_lines

        for text, style in tui_lines(model=self.model, extra=f"workdir {self.workdir}"):
            self.body_write(Text(text, style=style))
        self.body_write(
            Text("type a task; keep typing while it works to steer it · y/N/a at confirmations · / for commands",
                 style="#cc7000")
        )
        if self.messages:
            self.turns = len(self.messages)
            self.body_write(
                Text(
                    f"resumed session {self.store.id} ({len(self.messages)} messages)",
                    style="green",
                )
            )
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

    def body_write(self, renderable) -> None:
        self.query_one("#body", RichLog).write(renderable)

    def register_subagent(self, sub) -> None:
        self.subagents.append(sub)
        self.body_write(
            Text(f"spawned subagent[{sub.n}]: {sub.label}  ·  /subagents to list, "
                 f"/subagent {sub.n} to watch", style="cyan")
        )

    def refresh_status(self) -> None:
        pass  # status bar repaints on its own 1s tick; hook kept for callers

    def enter_confirm(self, command: str) -> None:
        self.confirming = True
        self.body_write(Text(f"run `{command}`?  answer below: y / N / a=always", style="bold yellow"))
        self.query_one(Input).placeholder = "y / N / a=always"

    def exit_confirm(self) -> None:
        self.confirming = False
        self.query_one(Input).placeholder = PLACEHOLDER

    def update_status(self, line: str) -> None:
        self.query_one("#status", Static).update(line)

    # ---- input routing ----

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
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
            if text == "/stop":
                self.action_interrupt()
            elif text == "/pause":
                self.action_pause()
            elif text.startswith("/model"):
                self._handle_model_command(text[len("/model") :].strip())
            elif text == "/compact":
                if self.busy:
                    self.body_write(Text("[/compact: wait until the agent is idle]", style="yellow"))
                elif not self.messages:
                    self.body_write(Text("[nothing to compact yet]", style="yellow"))
                else:
                    self.msg_q.put("\x00compact")
            elif text == "/yolo":
                self.runner.yolo = not self.runner.yolo
                self.body_write(
                    Text(
                        f"yolo {'ON — commands run without confirmation' if self.runner.yolo else 'OFF — commands need approval'}",
                        style="yellow",
                    )
                )
            elif text.startswith("/subagent"):
                rest = text[len("/subagent"):].lstrip()
                # /subagents (list)  ·  /subagent N (drill in)
                if rest.lstrip("s").strip() == "" and not rest[:1].isdigit():
                    if not self.subagents:
                        self.body_write(Text("no subagents spawned this session", style="yellow"))
                    else:
                        self.body_write(Text("subagents:", style="yellow"))
                        for s in self.subagents:
                            self.body_write(Text(f"  [{s.n}] {s.status:<7} {s.label}", style="yellow"))
                        self.body_write(Text("open one with /subagent <n>", style="yellow"))
                else:
                    arg = rest.lstrip("s").strip()
                    match = next((s for s in self.subagents if str(s.n) == arg), None)
                    if match:
                        self.push_screen(SubagentView(match))
                    else:
                        self.body_write(Text(f"no subagent {arg!r} — /subagents to list", style="red"))
            elif text == "/fx":
                fx = self.query_one("#fx")
                fx.display = not fx.display
                self.body_write(Text(f"fx {'on' if fx.display else 'off'}", style="yellow"))
            elif text.startswith("/rag"):
                arg = text[len("/rag"):].strip().lower()
                if arg in ("enable", "on"):
                    self.runner.rag = True
                elif arg in ("disable", "off"):
                    self.runner.rag = False
                elif arg:
                    self.body_write(Text("usage: /rag [enable|disable]", style="yellow")); return
                self.body_write(
                    Text(f"recall {'ENABLED — local code/docs/memory search available' if self.runner.rag else 'DISABLED'}",
                         style="yellow")
                )
            elif text == "/ctx" or text.startswith("/ctx "):
                from agent.core.compaction import ctx_command
                self.body_write(Text(ctx_command(self.runner, text[len("/ctx"):]), style="yellow"))
                return
            elif text == "/kv" or text.startswith("/kv "):
                self.body_write(Text(self.runner.kv_status(text[len("/kv"):]), style="yellow"))
                return
            elif text == "/art":
                self.runner.art = not self.runner.art
                self.body_write(Text(
                    f"image generation {'ENABLED — generate_image available' if self.runner.art else 'DISABLED'}"
                    + ("" if self.runner.art else "") + " (needs the 'art' extra: uv add mflux)",
                    style="yellow"))
                return
            elif text == "/status":
                self.body_write(
                    Text(
                        f"model={self.model}  yolo={self.runner.yolo}  rag={self.runner.rag}  "
                        f"net={self.runner.net}  workdir={self.workdir}  turns={self.turns}",
                        style="yellow",
                    )
                )
            else:
                self.body_write(
                    Text(
                        "commands: /yolo  /rag [enable|disable]  /ctx [<n>|max|auto]  /subagents  "
                        "/subagent <n>  /status  /compact  /model  /fx  /stop (Esc)  /pause (^P) · exit",
                        style="yellow",
                    )
                )
            return
        # attach staged multiline paste(s): typed instruction first, blob after
        if self._pastes:
            blob = "\n\n".join(self._pastes)
            self._pastes = []
            text = f"{text}\n\n{blob}" if text else blob
        if self.busy:
            self.io.steer_q.put(text)
            self.body_write(Text("[queued steering — applies at the next tool boundary]", style="magenta"))
        else:
            preview = text.splitlines()[0][:80] + (" …" if "\n" in text or len(text) > 80 else "")
            self.body_write(Text(f"\nyou> {preview}", style="bold"))
            self.msg_q.put(text)

    # ---- worker threads ----

    def _agent_loop(self) -> None:
        messages = self.messages
        while True:
            task = self.msg_q.get()
            if task is None:
                return
            self.busy = True
            try:
                if task == "\x00compact":
                    extra = (core.RAG_TOOLS if self.runner.rag else []) + \
                            (core.WEB_TOOLS if self.runner.net else [])
                    core.compact_messages(
                        self.client, messages, self.io, self.model,
                        store=self.store, max_tokens=self.max_tokens,
                        tools=core.TOOLS + [core.SUBAGENT_TOOL] + extra,
                    )
                    continue
                if task == "\x00continue":
                    # resume a mid-task session: if the model owes a turn, just
                    # run; if the last turn was the agent's, nudge it onward.
                    if messages and messages[-1].get("role") == "assistant":
                        messages.append({"role": "user", "content":
                            "[resumed] Continue the task from exactly where you left off."})
                else:
                    messages.append({"role": "user", "content": task})
                core.agent_turn(
                    self.client, messages, self.runner, self.io,
                    model=self.model, max_tokens=self.max_tokens, store=self.store,
                )
                # steering submitted after the final response starts a new turn
                leftovers = self.io.drain_steers()
                while leftovers:
                    messages.append({"role": "user", "content": "\n".join(leftovers)})
                    core.agent_turn(
                        self.client, messages, self.runner, self.io,
                        model=self.model, max_tokens=self.max_tokens, store=self.store,
                    )
                    leftovers = self.io.drain_steers()
            except anthropic.APIError as exc:
                self.io.notice(f"[api error] {exc}")
            except Exception as exc:  # keep the UI alive on agent bugs
                self.io.notice(f"[error] {type(exc).__name__}: {exc}")
            finally:
                self.busy = False
                self.turns = len(messages)
                paused = self.io.pause.is_set()
                if messages:
                    try:
                        self.store.save_transcript(messages, self.model, paused=paused)
                    except Exception as exc:
                        self.io.notice(f"[session save failed] {exc}")
                if paused:
                    self.call_from_thread(
                        self.body_write,
                        Text(f"[paused · resume: kas --resume {self.store.id}]", style="#ffb000"),
                    )
                    self.call_from_thread(self.exit)
                    return

    def _status_loop(self) -> None:
        url = self.base_url.rstrip("/") + "/v1/stats"
        online = True  # last known server reachability (for transition notices)
        while self._alive:
            try:
                s = httpx.get(url, timeout=2).json()
                up = True
            except Exception:
                s, up = {}, False
            # announce reachability transitions in the work view (reconnect mark)
            if up != online:
                try:
                    self.call_from_thread(self.body_write, Text(
                        "● reconnected to server" if up else "○ server unreachable — retrying…",
                        style="#3fb950" if up else "#ff5f5f"))
                except Exception:
                    return
                online = up
            age = s.get("last_ping_age")
            ping = ""
            if s.get("active") and age is not None:
                ping = f" · ping {age:g}s ago"
            stale = age is not None and age > 20  # pings should arrive ~every 5s
            if not up:
                conn, conn_style, work = "○ offline", "#ff5f5f", "server unreachable"
            elif s.get("active") and s.get("phase") == "prefill":
                conn = "◓ prefill" if not stale else "◓ prefill ⚠"
                conn_style = "#ffa657" if not stale else "#ff5f5f"  # amber, red if pings stalled
                work = (f"{s.get('processed', 0)}/{s.get('total', '?')} tok "
                        f"(cache {s.get('cached', 0)}) · {s.get('elapsed', 0):.0f}s{ping}")
            elif s.get("active"):
                conn = "◉ streaming" if not stale else "◉ streaming ⚠"
                conn_style = "#39d3e8" if not stale else "#ff5f5f"  # cyan, red if pings stalled
                work = (f"{s.get('generated', 0)} tok @ {s.get('tps', 0)} tok/s "
                        f"· {s.get('elapsed', 0):.0f}s{ping}")
            elif self.busy:
                conn, conn_style, work = "◌ tools", "#c792ea", "running tools"  # violet
            else:
                conn, conn_style, work = "● live", "#3fb950", "idle"  # green
            line = Text()
            line.append(conn + " ", style=conn_style)
            line.append(f"· {self.model} · yolo {'ON' if self.runner.yolo else 'off'} · {work}")
            queued = self.io.steer_q.qsize()
            if queued:
                line.append(f" · steering queued: {queued}")
            if self.subagents:
                running = sum(1 for a in self.subagents if a.status == "running")
                line.append(f" · subagents: {len(self.subagents)}"
                            + (f" ({running} running)" if running else ""))
            try:
                self.call_from_thread(self.update_status, line)
            except Exception:
                return
            time.sleep(1.0)
