"""Small Textual widgets and modal screens for the TUI: the model picker, the
subagent transcript viewer, the paste-preserving input, and the selectable log.
All are self-contained — they talk to the app (when at all) by duck-typed
attribute access, never by importing AgentApp.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option


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
        from scripts.select_model import model_info

        self._info = {m["id"]: m for m in model_info()}

    def _label(self, m: str) -> Text:
        meta = self._info.get(m, {})
        t = Text()
        t.append("● " if m == self._current else "  ", style="#3fb950")
        t.append(m)
        if meta:
            t.append(f"  {meta['size_h']}", style="#8a8a8a")
            if not meta["complete"]:
                t.append("  ⏳ partial", style="#ffa657")
        return t

    def compose(self) -> ComposeResult:
        with Vertical(id="ms-box"):
            yield Static("select a model  ·  ↑↓ + Enter  ·  Esc to cancel", id="ms-title")
            yield OptionList(*[Option(self._label(m), id=m) for m in self._models])

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SpecWizard(ModalScreen):
    """/spec step 1: pick what you're building (↑↓ + Enter, Esc to cancel).

    Returns the chosen project kind via dismiss(); the LLM follow-up questions
    and the spec itself happen in the normal chat afterward (see core.spec)."""

    CSS = """
    SpecWizard { align: center middle; }
    #sw-box { width: 70%; max-width: 70; height: auto; max-height: 80%;
              background: #1a0e00; border: round #ff9d00; padding: 1 2; }
    #sw-title { color: #ffb000; text-style: bold; padding-bottom: 1; }
    SpecWizard OptionList { background: #1a0e00; color: #ffb000; border: none; }
    SpecWizard OptionList > .option-list--option-highlighted {
        background: #ff9d00; color: #1a0e00; text-style: bold; }
    """
    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def compose(self) -> ComposeResult:
        from agent.core.spec import PROJECT_KINDS

        with Vertical(id="sw-box"):
            yield Static("/spec — what are you building?  ·  ↑↓ + Enter  ·  Esc", id="sw-title")
            yield OptionList(*[Option(k, id=k) for k in PROJECT_KINDS])

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
            yield Static(
                f"subagent[{self._sub.n}] · {self._sub.status} · {self._sub.label}  (Esc to close)",
                id="sv-title",
            )
            log = RichLog(wrap=True, markup=False, highlight=False)
            yield log

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        for line in self._sub.buffer or ["(no captured output)"]:
            log.write(Text(line, style="#cc7000"))

    def action_dismiss(self) -> None:
        self.dismiss(None)


class Composer(ModalScreen):
    """A full multi-line editor for long / pasted input — VIEW, edit, and send.

    A one-line Input can't show pasted multiline text; this modal does. It opens
    automatically on a multiline paste (pre-filled with it) and on demand via
    Ctrl+O. Enter inserts newlines (real multi-line editing); Ctrl+S sends.

    Closing WITHOUT sending never loses work: on_unmount restages the current text
    as a draft (reopen with Ctrl+O). This matters because the app's priority
    `escape` binding dismisses modals with no result, so we can't rely on a result
    value to carry the draft back — we push it to the app ourselves.
    """

    CSS = """
    Composer { align: center middle; }
    #cp-box { width: 90%; height: 80%; background: #1a0e00; border: round #ff9d00; padding: 1 2; }
    #cp-title { color: #ffb000; text-style: bold; padding-bottom: 1; }
    Composer TextArea { background: #0a0500; color: #ffb000; height: 1fr; border: none; }
    """
    BINDINGS = [Binding("ctrl+s", "send", "send", priority=True)]

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text  # kept in sync with the editor; read by on_unmount
        self._sent = False

    def compose(self) -> ComposeResult:
        with Vertical(id="cp-box"):
            yield Static(
                "composer  ·  Enter = newline  ·  Ctrl+S send  ·  Esc keep as draft",
                id="cp-title",
            )
            yield TextArea(self._text, id="cp-area", soft_wrap=True)

    def on_mount(self) -> None:
        area = self.query_one(TextArea)
        area.focus()
        area.move_cursor(area.document.end)  # land at the end of the pasted text

    def on_text_area_changed(self, event) -> None:
        self._text = event.text_area.text

    def action_send(self) -> None:
        self._sent = True
        self.dismiss(("send", self.query_one(TextArea).text))

    def on_unmount(self) -> None:
        # Any non-send close (Esc, ctrl+c, etc.) preserves the text as a draft.
        if not self._sent and self._text.strip():
            self.app.stage_paste(self._text)


class PasteInput(Input):
    """Single-line Input that doesn't shred a big/multiline paste.

    Stock Input._on_paste keeps only splitlines()[0]. We intercept a multiline (or
    long) paste and spill it to a temp file, dropping a compact `@file` reference
    inline (see AgentApp.spill_paste_to_file) — robust even when the terminal has
    no bracketed-paste. Ctrl+O still opens the Composer for composing by hand.
    """

    def _on_paste(self, event) -> None:
        # A big/multiline paste is spilled to a temp file and referenced inline
        # (see AgentApp.spill_paste_to_file) rather than flooded into the one-line
        # field. Short single-line pastes insert normally.
        if event.text and ("\n" in event.text or len(event.text) > 200):
            event.stop()
            self.app.spill_paste_to_file(event.text)
            return
        super()._on_paste(event)

    def on_key(self, event) -> None:
        # /fx browse mode: Tab/Space/→/↓ flip to the next effect, Shift+Tab/←/↑ to
        # the previous, on the live bar. Enter (keep) and Esc (cancel) are handled
        # by on_input_submitted / action_interrupt; everything else is swallowed so
        # the input stays clean while flipping.
        if getattr(self.app, "_fx_browsing", False):
            if event.key in ("enter", "escape"):
                return
            event.stop()
            event.prevent_default()
            if event.key in ("tab", "space", "right", "down"):
                self.app.fx_browse_step(1)
            elif event.key in ("shift+tab", "left", "up"):
                self.app.fx_browse_step(-1)
            return
        # Tab autocompletes a /command (shell-style: extend to the shared prefix,
        # then list the options). Handled here so it beats focus-navigation.
        if event.key == "tab" and not getattr(self.app, "confirming", False):
            if self.value.startswith("/"):
                event.stop()
                event.prevent_default()
                self._tab_complete()
            return
        # During a command-confirmation, a single y / n / a answers it (no Enter)
        # and is NOT typed into the field. Handled here (the focused widget) so it
        # beats the Input's own character insertion; otherwise keys are normal.
        ch = (event.character or "").lower()
        if getattr(self.app, "confirming", False) and ch in ("y", "n", "a"):
            event.stop()
            event.prevent_default()
            self.app.action_confirm(ch)

    def _tab_complete(self) -> None:
        """Complete the current /command against the app's candidate list."""
        import os

        cur = self.value
        cands = [c for c in getattr(self.app, "_completions", []) if c.startswith(cur)]
        if not cands:
            return
        shared = os.path.commonprefix(cands)
        if len(shared) > len(cur):
            # extend to the shared prefix; trail a space if a subcommand follows
            if any(c.startswith(shared + " ") for c in cands):
                shared += " "
            self.value = shared
            self.cursor_position = len(self.value)
        elif len(cands) > 1:
            # at a branch point — show the options; and if the typed text is itself
            # a complete command, trail a space so its argument can follow
            self.app.body_write(Text("  " + "    ".join(cands), style="dim"))
            if cur in cands and not cur.endswith(" "):
                self.value = cur + " "
                self.cursor_position = len(self.value)
        elif any(c.startswith(cur + " ") for c in self.app._completions):
            self.value = cur + " "  # single exact command that takes an argument
            self.cursor_position = len(self.value)


class SelectableRichLog(RichLog):
    """RichLog with mouse text selection.

    Stock RichLog supports neither extracting nor *painting* a selection. Two
    overrides fix that:

    - get_selection: map a Selection back to text. Its `lines` are the rendered
      visual lines (Strips), which is the coordinate space selections live in.
    - render_line: stock RichLog.render_line returns the raw strip and never
      applies the selection style, so a highlight was invisible even though the
      selection state was correct (you could "select" but saw nothing). We paint
      the `screen--selection` component style over the selected span per line,
      mirroring what the Log widget does.
    """

    ALLOW_SELECT = True
    # Don't steal focus when clicked to start a selection — the input stays
    # focused so you can keep typing. Selection is screen-level (not focus-bound)
    # and the mouse wheel still scrolls the widget under the pointer.
    can_focus = False

    def get_selection(self, selection) -> tuple[str, str] | None:
        text = "\n".join(strip.text for strip in self.lines)
        return selection.extract(text), "\n"

    def render_line(self, y: int):
        from textual.strip import Strip

        scroll_x, scroll_y = self.scroll_offset
        content_y = scroll_y + y
        line = self._render_line(content_y, scroll_x, self.scrollable_content_region.width)
        strip = line.apply_style(self.rich_style)
        # Tag each cell with its CONTENT coordinate (stock RichLog doesn't), so a
        # drag maps to the right lines — without this the selection latched onto
        # the wrong content (e.g. the banner) regardless of where you dragged.
        strip = strip.apply_offsets(scroll_x, content_y)
        selection = self.text_selection
        if selection is None:
            return strip
        span = selection.get_span(content_y)
        if span is None:
            return strip
        start, end = span
        width = strip.cell_length
        # x-coords are content columns; the strip starts at scroll_x
        start = min(max(0, start - scroll_x), width)
        end = width if end == -1 else min(max(0, end - scroll_x), width)
        if end <= start:
            return strip
        from rich.segment import Segment

        sel_style = self.screen.get_component_rich_style("screen--selection")
        selected = strip.crop(start, end)
        # post_style overlays the selection ON TOP of each segment's own style, so
        # it wins even over content that sets its own background (e.g. the banner).
        selected = Strip(
            Segment.apply_style(list(selected), post_style=sel_style), selected.cell_length
        )
        return Strip.join([strip.crop(0, start), selected, strip.crop(end, width)])
