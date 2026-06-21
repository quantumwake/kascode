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

try:
    import psutil  # optional ('stats' extra): CPU/RAM/disk/net for the /stats panel
except ImportError:
    psutil = None
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
            "/ctx", "/ctx max", "/ctx auto", "/kv", "/art", "/stats", "/fx", "/theme", "/compact",
            "/supercharge", "/stop", "/pause", "/model", "exit"]


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
    """A one-row ambient CRT animation strip that REACTS to what the agent is
    doing — the palette and effect track the app's fx_mode (idle / prefill /
    generating / tools / offline). Toggle with /fx. One line, so it's cheap.

      idle       amber twinkle (calm)
      prefill    orange breathing pulse (warming up)
      generating cyan equalizer wave, faster (tokens flowing)
      tools      violet comet sweep (working)
      offline    dim red flatline
    """

    GLYPHS = "·✦*°⋆+•∙"
    BARS = " ▁▂▃▄▅▆▇█"
    BRAILLE = " ⠁⠃⠇⡇⣇⣧⣷⣿"
    # palette per state, dim → bright (last entry matches the status-line colour)
    PALETTES = {
        "idle":       ["#3a2000", "#7a4500", "#b86800", "#ffb000", "#ffd470"],  # amber
        "prefill":    ["#3a1e00", "#7a3d00", "#b85c00", "#ffa657", "#ffd0a0"],  # orange
        "generating": ["#06363b", "#0a6b74", "#1aa6b3", "#39d3e8", "#9af2ff"],  # cyan
        "tools":      ["#2a1640", "#4f2d80", "#7a45c0", "#c792ea", "#e9d4ff"],  # violet
        "offline":    ["#2a0000", "#5a0d0d", "#8a1f1f", "#ff5f5f", "#ffb0b0"],  # red
    }
    # Colour schemes the rotating states cycle through. Most are MULTI-HUE mixes
    # (red/orange/yellow/green/blue/white together) so the bar bursts with colour,
    # plus a few mono ramps for contrast.
    PALETTE_POOL = [
        ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#0a84ff"],  # rgb (red→orange→yellow→green→blue)
        ["#e63946", "#f3a712", "#06d6a0", "#118ab2", "#9b5de5"],  # spectrum
        ["#ff2d95", "#feec00", "#00f5d4", "#00bbf9", "#9b5de5"],  # neon
        ["#ff3b30", "#ff9500", "#ffffff", "#00c8ff", "#0a84ff"],  # fire→ice (with white)
        ["#c81d11", "#ff5e00", "#ffae00", "#ffe600", "#ffffff"],  # warm (red→white-hot)
        ["#0a84ff", "#00b4d8", "#34c759", "#90e0ef", "#ffffff"],  # cool (blue→green→white)
        ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff"],  # synthwave
        ["#d00000", "#ffba08", "#3f88c5", "#52b788", "#e0aaff"],  # jewel
        ["#ff5fa8", "#ff9d5f", "#ffe85f", "#5fe8a8", "#5fa8ff"],  # candy
        ["#ff0040", "#ff8c00", "#ffe600", "#00d26a", "#3a86ff"],  # rainbow
        ["#39ff14", "#00e5ff", "#fffb00", "#ff124f", "#ffffff"],  # vivid mix
        ["#3a2000", "#7a4500", "#b86800", "#ffb000", "#ffd470"],  # amber ramp
        ["#0a2a4a", "#155a8a", "#2a8ac8", "#4ec3f0", "#a8e8ff"],  # ice ramp
        ["#06340a", "#0a7a1a", "#1aa82a", "#39e85a", "#9affb0"],  # matrix ramp
        ["#222222", "#555555", "#888888", "#bbbbbb", "#ffffff"],  # mono
    ]
    # Per-state effect POOLS are DISJOINT so each state is instantly recognizable:
    # idle = calm/ambient (slow drift, rotating colourful palettes); generating =
    # energetic/flowing; tools = mechanical/marching. Working states are FAST and
    # wear a FIXED signature colour (see PALETTES + _tick) so it's obvious the
    # agent is busy. prefill is a real progress bar; offline is a flatline.
    POOLS = {
        "idle":       ("twinkle", "pulse", "plasma", "starfield", "fire", "heartbeat", "bounce",
                       "dna", "ripple", "rain", "sine", "lava", "aurora", "throb", "glimmer",
                       "confetti", "noise", "firefly"),
        "prefill":    ("progress",),
        "generating": ("wave", "vu", "spectrum", "zigzag", "scanline", "ladder", "rotor",
                       "braille", "fireworks", "symbars"),
        "tools":      ("comet", "larson", "snake", "marquee", "binary", "glitch", "wipe",
                       "morse", "worm", "crossing", "parallax", "wavefront", "meteor"),
        "offline":    ("flat",),
    }
    # Per-mode animation speed (float step added to self._t each tick). idle drifts
    # gently; working states race so the difference reads at a glance.
    MODE_SPEED = {"idle": 0.5, "prefill": 1.0, "generating": 2.0, "tools": 1.6, "offline": 0.4}
    # Named colour themes for `/theme <name>` — pins the whole bar to one palette
    # (overrides idle's rotation + the working signature). `/theme auto` clears it.
    THEMES = {
        "matrix":    ["#06340a", "#0a7a1a", "#1aa82a", "#39e85a", "#9affb0"],
        "amber":     ["#3a2000", "#7a4500", "#b86800", "#ffb000", "#ffd470"],
        "ice":       ["#0a2a4a", "#155a8a", "#2a8ac8", "#4ec3f0", "#a8e8ff"],
        "fire":      ["#c81d11", "#ff5e00", "#ffae00", "#ffe600", "#ffffff"],
        "neon":      ["#ff2d95", "#feec00", "#00f5d4", "#00bbf9", "#9b5de5"],
        "synthwave": ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff"],
        "rainbow":   ["#ff0040", "#ff8c00", "#ffe600", "#00d26a", "#3a86ff"],
        "purple":    ["#1a0a3a", "#3d1d7a", "#6a2dc0", "#a05cf0", "#d4b0ff"],
        "mono":      ["#222222", "#555555", "#888888", "#bbbbbb", "#ffffff"],
    }
    # effects a user can pin via `/fx <name>`
    EFFECTS = ("twinkle", "pulse", "wave", "comet", "plasma", "scanline", "fire", "starfield",
               "braille", "progress", "heartbeat", "flat", "larson", "bounce", "vu", "dna",
               "ripple", "rain", "marquee", "glitch", "sine", "meteor", "snake", "spectrum",
               "wipe", "binary", "firefly", "fireworks", "zigzag", "throb", "morse", "lava",
               "worm", "aurora", "crossing", "glimmer", "ladder", "rotor", "parallax",
               "wavefront", "symbars", "confetti", "noise")

    def __init__(self) -> None:
        super().__init__("", id="fx")
        self._t = 0
        self._tf = 0.0            # float clock; per-mode speed advances it (see _tick)
        self._frame = 0           # ticks since mount, for rotation timing
        self._rotate_at = 0       # frame to switch effect on
        self._mode: str | None = None
        self._effect = "twinkle"
        self._cur: str | None = None  # last effect actually rendered (to reset buffers on change)
        self._pin: str | None = None  # forced effect (/fx <name>); None = rotate
        self._palette: list[str] | None = None  # current colour scheme
        self._theme: list[str] | None = None  # /theme override: pins palette for all states
        self._theme_name: str | None = None   # name of the active /theme (None = auto)
        self._cells: list[float] = []
        self._glyphs: list[str] = []
        self._stars: list[list[float]] = []

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)

    def _stats(self) -> dict:
        return getattr(self.app, "fx_stats", None) or {}

    def set_theme(self, arg: str) -> str:
        """`/theme [<name>|auto|list]` — pin the bar's palette, or restore auto."""
        name = (arg or "").strip().lower()
        names = ", ".join(self.THEMES)
        if name in ("", "list"):
            return f"themes: {names} · auto — current: {self._theme_name or 'auto'} (e.g. /theme matrix)"
        if name in ("auto", "off", "none"):
            self._theme = self._theme_name = None
            self._palette = None  # force a fresh pick next tick
            return "theme: auto — idle rotates colours; working states show their signature colour"
        if name in self.THEMES:
            self._theme = list(self.THEMES[name])
            self._theme_name = name
            self._palette = self._theme
            return f"theme: {name}"
        return f"unknown theme {name!r} — try: {names}, auto"

    def _tick(self) -> None:
        w = max(0, self.size.width)
        if w == 0:
            return
        self._frame += 1
        mode = getattr(self.app, "fx_mode", "idle")
        if mode not in self.POOLS:
            mode = "idle"
        # rotate on a state change or when the dwell timer elapses. idle dwells
        # longer (calm); working states cycle quicker so the bar feels alive.
        dwell = random.randint(120, 200) if mode == "idle" else random.randint(70, 120)
        if mode != self._mode or self._frame >= self._rotate_at or self._palette is None:
            self._mode = mode
            self._rotate_at = self._frame + dwell
            if not self._pin:
                pool = self.POOLS[mode]
                self._effect = random.choice([e for e in pool if e != self._effect] or list(pool))
            # Colour policy (a /theme override wins outright):
            #   • theme set → that palette everywhere
            #   • idle      → rotate through the colourful pool (variety = calm/alive)
            #   • working   → FIXED signature colour per state, so busy is obvious
            if self._theme is not None:
                self._palette = self._theme
            elif mode == "idle":
                self._palette = random.choice(self.PALETTE_POOL)
            else:
                self._palette = self.PALETTES[mode]
        effect = self._pin or self._effect
        shades = self._theme or self._palette or self.PALETTES["idle"]
        # Effects share the _cells/_glyphs/_stars scratch buffers, so reset them
        # whenever the effect changes — the new one re-inits them at the current
        # width (prevents stale-length IndexErrors across effects).
        if effect != self._cur:
            self._cells, self._glyphs, self._stars = [], [], []
            self._cur = effect
        self._tf += self.MODE_SPEED.get(mode, 1.0)
        self._t = int(self._tf)
        fn = getattr(self, "_" + effect, self._twinkle)
        self.update(fn(w, shades))

    def _twinkle(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or len(self._glyphs) != w:
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
            t.append(" " if v < 0.12 else self._glyphs[i], style=shades[min(4, int(v * 5))])
        return t

    def _wave(self, w: int, shades: list[str]) -> Text:
        # speed tracks live decode rate — fast generation visibly rips
        tps = self._stats().get("tps") or 12
        spd = 0.12 + min(40.0, float(tps)) / 40.0 * 0.4
        t = Text()
        for col in range(w):
            y = math.sin(col * 0.25 + self._t * spd) * 0.5 + math.sin(col * 0.07 - self._t * 0.13) * 0.5
            idx = max(0, min(len(self.BARS) - 1, int((y + 1) / 2 * (len(self.BARS) - 1))))
            t.append(self.BARS[idx], style=shades[1 + (idx * 3) // len(self.BARS)])
        return t

    def _comet(self, w: int, shades: list[str]) -> Text:
        pos = (self._t * 2) % (w + 24) - 12
        t = Text()
        for i in range(w):
            d = abs(i - pos)
            t.append(" " if d > 6 else ("═" if d <= 2 else "─"), style=shades[max(0, 4 - d)])
        return t

    def _pulse(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            b = (math.sin(self._t * 0.12 + col * 0.06) + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _flat(self, w: int, shades: list[str]) -> Text:
        on = (self._t // 6) % 2 == 0
        return Text("".join("·" if (i % 6 == 0 and on) else " " for i in range(w)), style=shades[1])

    def _plasma(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = (math.sin(col * 0.20 + self._t * 0.10)
                 + math.sin(col * 0.07 - self._t * 0.07)
                 + math.sin((col + self._t) * 0.13)) / 3
            b = (v + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _scanline(self, w: int, shades: list[str]) -> Text:
        head = (self._t * 1.5) % (w + 1)
        t = Text()
        for i in range(w):
            d = abs(i - head)
            if d < 1.5:
                ch, sh = "█", 4
            elif d < 4:
                ch, sh = "▓", 3
            elif d < 8:
                ch, sh = "░", 2
            else:
                ch, sh = ("·" if i % 5 == 0 else " "), 0
            t.append(ch, style=shades[sh])
        return t

    def _fire(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w:
            self._cells = [0.0] * w
        for i in range(w):
            self._cells[i] = max(0.0, self._cells[i] * 0.7 + random.uniform(-0.08, 0.08))
            if random.random() < 0.15:
                self._cells[i] = random.random()
        t = Text()
        for v in self._cells:
            idx = min(len(self.BARS) - 1, int(v * (len(self.BARS) - 1)))
            t.append(self.BARS[idx], style=shades[min(4, int(v * 5))])
        return t

    def _starfield(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or not self._stars:
            self._cells = [0.0] * w
            self._stars = [[random.uniform(0, w), random.uniform(0.2, 1.0)]
                           for _ in range(max(3, w // 12))]
        glyph = [" "] * w
        sh = [0] * w
        for s in self._stars:
            s[0] += s[1] * 0.6  # drift; brighter (nearer) stars move faster
            if s[0] >= w:
                s[0], s[1] = 0.0, random.uniform(0.2, 1.0)
            i = int(s[0])
            if 0 <= i < w:
                glyph[i] = random.choice(self.GLYPHS) if s[1] > 0.7 else "·"
                sh[i] = min(4, int(s[1] * 5))
        t = Text()
        for ch, s in zip(glyph, sh):
            t.append(ch, style=shades[s])
        return t

    def _braille(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            y = math.sin(col * 0.3 + self._t * 0.25) * 0.5 + math.sin(col * 0.1 - self._t * 0.1) * 0.5
            idx = max(0, min(len(self.BRAILLE) - 1, int((y + 1) / 2 * (len(self.BRAILLE) - 1))))
            t.append(self.BRAILLE[idx], style=shades[1 + (idx * 3) // len(self.BRAILLE)])
        return t

    def _progress(self, w: int, shades: list[str]) -> Text:
        # real prefill progress when the server reports processed/total; else a
        # gentle indeterminate sweep.
        s = self._stats()
        total, done = s.get("total") or 0, s.get("processed") or 0
        t = Text()
        if total:
            fill = int(done / total * w)
            for i in range(w):
                if i < fill:
                    t.append("█", style=shades[3])
                elif i == fill:
                    t.append("▌", style=shades[4])
                else:
                    t.append("·" if i % 4 == 0 else " ", style=shades[1])
        else:
            head = (self._t * 1.2) % (w + 8)
            for i in range(w):
                t.append("█" if abs(i - head) < 3 else ("·" if i % 4 == 0 else " "),
                         style=shades[3 if abs(i - head) < 3 else 1])
        return t

    def _heartbeat(self, w: int, shades: list[str]) -> Text:
        # a traveling EKG spike over a dim baseline
        pos = int(self._t) % w if w else 0
        t = Text()
        for i in range(w):
            d = (i - pos) % w
            if d == 0:
                ch, sh = "█", 4
            elif d == 1:
                ch, sh = "▆", 3
            elif d == 2:
                ch, sh = "▂", 2
            else:
                ch, sh = "─", 1
            t.append(ch, style=shades[sh])
        return t

    def _larson(self, w: int, shades: list[str]) -> Text:
        # Cylon/KITT scanner — a bright dot bouncing L↔R with a trailing glow.
        period = max(1, 2 * (w - 1))
        p = self._t % period
        pos = p if p < w else period - p
        glyph = {0: "█", 1: "▓", 2: "▒", 3: "░"}
        t = Text()
        for i in range(w):
            d = abs(i - pos)
            t.append(glyph.get(d, " "), style=shades[max(0, 4 - d)])
        return t

    def _bounce(self, w: int, shades: list[str]) -> Text:
        period = max(1, 2 * (w - 1))
        p = self._t % period
        pos = p if p < w else period - p
        t = Text()
        for i in range(w):
            t.append("●" if i == pos else ("·" if i % 8 == 0 else " "),
                     style=shades[4 if i == pos else 1])
        return t

    def _vu(self, w: int, shades: list[str]) -> Text:
        # random equalizer bars that jump and decay (music-meter feel)
        if len(self._cells) != w:
            self._cells = [0.0] * w
        for i in range(w):
            self._cells[i] = max(0.0, self._cells[i] - 0.12)
            if random.random() < 0.10:
                self._cells[i] = random.random()
        t = Text()
        for v in self._cells:
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _dna(self, w: int, shades: list[str]) -> Text:
        # two interleaved strands
        t = Text()
        for col in range(w):
            a = math.sin(col * 0.3 + self._t * 0.15)
            b = math.sin(col * 0.3 + self._t * 0.15 + math.pi)
            ya = int((a + 1) / 2 * (len(self.BARS) - 1))
            yb = int((b + 1) / 2 * (len(self.BARS) - 1))
            if ya >= yb:
                t.append(self.BARS[ya], style=shades[3])
            else:
                t.append(self.BARS[yb], style=shades[2])
        return t

    def _ripple(self, w: int, shades: list[str]) -> Text:
        c = w // 2
        t = Text()
        for i in range(w):
            d = abs(i - c)
            v = (math.sin(d * 0.6 - self._t * 0.3) + 1) / 2
            v *= max(0.15, 1 - d / (w / 1.5 or 1))
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _rain(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or len(self._glyphs) != w:
            self._cells = [0.0] * w
            self._glyphs = [" "] * w
        for i in range(w):
            self._cells[i] *= 0.75
        for _ in range(max(1, w // 28)):
            i = random.randrange(w)
            self._cells[i] = 1.0
            self._glyphs[i] = random.choice("╷│┃╿")
        t = Text()
        for i in range(w):
            v = self._cells[i]
            t.append(" " if v < 0.15 else self._glyphs[i], style=shades[min(4, int(v * 5))])
        return t

    def _marquee(self, w: int, shades: list[str]) -> Text:
        pat = "▰▰▱ "
        off = self._t % len(pat)
        t = Text()
        for i in range(w):
            ch = pat[(i + off) % len(pat)]
            t.append(ch, style=shades[3 if ch == "▰" else 1])
        return t

    def _glitch(self, w: int, shades: list[str]) -> Text:
        chars = "▚▞▌▐░▒█┃╳"
        t = Text()
        for i in range(w):
            if random.random() < 0.08:
                t.append(random.choice(chars), style=shades[random.randint(2, 4)])
            else:
                t.append("·" if i % 7 == 0 else " ", style=shades[1])
        return t

    def _sine(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            y = (math.sin(col * 0.2 + self._t * 0.2) + 1) / 2
            t.append("•" if y > 0.55 else ("·" if y > 0.2 else " "), style=shades[min(4, int(y * 5))])
        return t

    def _meteor(self, w: int, shades: list[str]) -> Text:
        pos = (self._t * 2) % (w + 30) - 15
        t = Text()
        for i in range(w):
            d = pos - i  # tail trails to the left
            if d == 0:
                t.append("◉", style=shades[4])
            elif 0 < d < 12:
                t.append("═" if d < 2 else "─", style=shades[max(0, 4 - d // 3)])
            else:
                t.append(" ")
        return t

    def _snake(self, w: int, shades: list[str]) -> Text:
        seg = 8
        head = self._t % w if w else 0
        t = Text()
        for i in range(w):
            d = (head - i) % w
            t.append("█" if d < seg else " ", style=shades[max(0, 4 - d // 2)] if d < seg else shades[0])
        return t

    # --- second wave of effects -------------------------------------------

    def _spectrum(self, w: int, shades: list[str]) -> Text:
        n = len(shades)
        t = Text()
        for i in range(w):
            k = (i + self._t) % (2 * n - 2)
            t.append("█", style=shades[k if k < n else 2 * n - 2 - k])
        return t

    def _wipe(self, w: int, shades: list[str]) -> Text:
        period = max(1, 2 * w)
        p = self._t % period
        edge = p if p < w else period - p
        t = Text()
        for i in range(w):
            t.append("█" if i < edge else ("▌" if i == edge else " "),
                     style=shades[4 if i == edge else (3 if i < edge else 0)])
        return t

    def _binary(self, w: int, shades: list[str]) -> Text:
        if len(self._glyphs) != w:
            self._glyphs = [random.choice("01  ") for _ in range(w)]
        if self._t % 2 == 0:
            self._glyphs = [random.choice("01  ")] + self._glyphs[:-1]
        t = Text()
        for ch in self._glyphs:
            t.append(ch, style=shades[3 if ch in "01" else 0])
        return t

    def _firefly(self, w: int, shades: list[str]) -> Text:
        if len(self._stars) < 2:
            self._stars = [[random.uniform(0, w - 1), random.uniform(-1, 1)] for _ in range(max(2, w // 22))]
        cells, sh = [" "] * w, [0] * w
        for s in self._stars:
            s[0] += s[1] * 0.7
            if not (0 <= s[0] < w):
                s[1] = -s[1]
                s[0] = max(0, min(w - 1, s[0]))
            if random.random() < 0.1:
                s[1] += random.uniform(-0.3, 0.3)
            j = int(s[0])
            cells[j], sh[j] = random.choice("✦✺*•"), 4
        t = Text()
        for ch, k in zip(cells, sh):
            t.append(ch, style=shades[k])
        return t

    def _fireworks(self, w: int, shades: list[str]) -> Text:
        phase, cyc = self._t % 40, self._t // 40
        c = (cyc * 37) % max(1, w)
        t = Text()
        for i in range(w):
            d = abs(i - c)
            if phase < 3 and d == 0:
                t.append("✺", style=shades[4])
            elif 0 < phase < 18 and d == phase:
                t.append(random.choice("*✦•"), style=shades[max(0, 4 - phase // 5)])
            else:
                t.append(" ")
        return t

    def _zigzag(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            tw = (col + self._t) % 8
            h = tw if tw < 4 else 8 - tw
            t.append(self.BARS[1 + h], style=shades[1 + (h * 3) // 5])
        return t

    def _throb(self, w: int, shades: list[str]) -> Text:
        c = (w / 2) or 1
        b = (math.sin(self._t * 0.2) + 1) / 2
        t = Text()
        for i in range(w):
            v = max(0.0, b - abs(i - c) / c * 0.8)
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _morse(self, w: int, shades: list[str]) -> Text:
        pat = "█ ███ █ █   "
        off = self._t % len(pat)
        t = Text()
        for i in range(w):
            ch = pat[(i + off) % len(pat)]
            t.append(ch, style=shades[3 if ch != " " else 0])
        return t

    def _lava(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = (math.sin(col * 0.10 + self._t * 0.05) + math.sin(col * 0.04 - self._t * 0.03)) / 2
            b = (v + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _worm(self, w: int, shades: list[str]) -> Text:
        seg = 6
        head = self._t % (w + seg)
        t = Text()
        for i in range(w):
            d = head - i
            inside = 0 <= d < seg
            t.append(("●" if d == 0 else "•") if inside else " ",
                     style=shades[max(0, 4 - d)] if inside else shades[0])
        return t

    def _aurora(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = (math.sin(col * 0.08 + self._t * 0.06) + math.sin(col * 0.15 + self._t * 0.03)
                 + math.sin(col * 0.03 - self._t * 0.04)) / 3
            b = (v + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _crossing(self, w: int, shades: list[str]) -> Text:
        a = (self._t * 2) % (w + 8) - 4
        b = w - ((self._t * 2) % (w + 8) - 4)
        t = Text()
        for i in range(w):
            d = min(abs(i - a), abs(i - b))
            t.append(" " if d > 4 else ("◆" if d == 0 else "─"), style=shades[max(0, 4 - d)])
        return t

    def _glimmer(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for _i in range(w):
            if random.random() < 0.06:
                t.append(random.choice("✦✺*"), style=shades[4])
            else:
                t.append(" ", style=shades[0])
        return t

    def _ladder(self, w: int, shades: list[str]) -> Text:
        n = len(self.BARS)
        t = Text()
        for col in range(w):
            h = (col * 2 + self._t) % (2 * (n - 1))
            h = h if h < n else 2 * (n - 1) - h
            t.append(self.BARS[h], style=shades[min(4, (h * 5) // n)])
        return t

    def _rotor(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = math.sin((col - self._t) * 0.4) * math.cos(self._t * 0.1)
            b = (v + 1) / 2
            t.append(self.BARS[int(b * (len(self.BARS) - 1))], style=shades[min(4, int(b * 5))])
        return t

    def _parallax(self, w: int, shades: list[str]) -> Text:
        out, sh = [" "] * w, [0] * w
        for speed, ch, s in ((3, "·", 1), (2, "•", 2), (1, "✦", 4)):
            for k in range(0, w, 6):
                pos = (k + self._t * speed) % w
                out[pos], sh[pos] = ch, s
        t = Text()
        for ch, s in zip(out, sh):
            t.append(ch, style=shades[s])
        return t

    def _wavefront(self, w: int, shades: list[str]) -> Text:
        pos = self._t % (w + 10) - 5
        n = len(self.BARS)
        t = Text()
        for i in range(w):
            d = abs(i - pos)
            t.append(self.BARS[n - 1 - d] if d < n else " ", style=shades[max(0, 4 - d)])
        return t

    def _symbars(self, w: int, shades: list[str]) -> Text:
        c = w // 2
        t = Text()
        for i in range(w):
            v = (math.sin(abs(i - c) * 0.3 - self._t * 0.2) + 1) / 2
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _confetti(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or len(self._glyphs) != w:
            self._cells, self._glyphs = [0.0] * w, [" "] * w
        for i in range(w):
            self._cells[i] *= 0.85
        for _ in range(max(1, w // 20)):
            j = random.randrange(w)
            self._cells[j], self._glyphs[j] = 1.0, random.choice("▪▫◆●*✦")
        t = Text()
        for i in range(w):
            v = self._cells[i]
            t.append(" " if v < 0.15 else self._glyphs[i], style=shades[min(4, int(v * 5))])
        return t

    def _noise(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for _i in range(w):
            r = random.random()
            t.append(random.choice(" ░▒▓"), style=shades[min(4, int(r * 5))])
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
            # cumulative session token totals, for the /stats panel
            self.app.tok_in += usage.input_tokens
            self.app.tok_out += usage.output_tokens
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
    #topstats { dock: top; height: 1; background: #140a00; color: #ffb000; padding: 0 1; display: none; }
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
        self.fx_mode = "idle"  # current state, drives the ambient FxBar animation
        self.fx_stats: dict = {}  # live tps/processed/total for data-driven fx
        self.tok_in = 0          # cumulative session prompt tokens (for /stats)
        self.tok_out = 0         # cumulative session generated tokens
        self.stats_on = False    # /stats panel visible
        self._io_prev: tuple | None = None  # (disk_bytes, net_bytes, t) for IO rates
        self.confirming = False
        self.turns = 0
        self._alive = True
        self._pastes: list[str] = []  # staged multiline pastes, sent with next message
        self.subagents: list = []  # SubagentIO registry (this session)

    def compose(self) -> ComposeResult:
        yield Static("", id="topstats")  # /stats panel, docked top (hidden by default)
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
        from scripts.select_model import model_info

        info = {m["id"]: m for m in model_info()}
        cur, tgt = info.get(self.model, {}), info.get(target, {})
        self.body_write(Text(
            f"[switching {self.model.split('/')[-1]} ({cur.get('size_h', '?')}) → "
            f"{target.split('/')[-1]} ({tgt.get('size_h', '?')}) — offloads the current "
            "model, then loads the new one…]", style="yellow"))

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

    # ---- /stats panel ----

    @staticmethod
    def _fmt_bytes(n: float) -> str:
        n = float(n)
        for u in ("B", "K", "M", "G"):
            if n < 1024 or u == "G":
                return f"{n:.0f}{u}" if u in ("B", "K") else f"{n:.1f}{u}"
            n /= 1024
        return f"{n:.1f}G"

    @staticmethod
    def _gauge(frac: float, width: int = 6) -> Text:
        frac = max(0.0, min(1.0, frac))
        filled = int(round(frac * width))
        color = "#3fb950" if frac < 0.7 else ("#ffa657" if frac < 0.9 else "#ff5f5f")
        t = Text("▕", style="#555555")
        t.append("█" * filled + "░" * (width - filled), style=color)
        t.append("▏", style="#555555")
        return t

    def _stats_line(self, s: dict | None) -> Text:
        s = s or {}
        L, V, C = "#8a6a2a", "#ffb000", "#39d3e8"  # label / value / accent colours
        t = Text()
        t.append("▌ ", style="#ff9d00")
        t.append(self.model.split("/")[-1], style="bold #ffb000")
        t.append("  ")
        # context window usage
        cl = s.get("context_length") or getattr(self.runner, "context_limit", None)
        used = getattr(self.runner, "last_input_tokens", 0)
        if cl:
            t.append("ctx ", style=L)
            t.append_text(self._gauge(used / cl))
            t.append(f" {used // 1000}k/{cl // 1000}k  ", style=V)
        if s.get("layers"):
            t.append("layers ", style=L); t.append(f"{s['layers']}  ", style=V)
        # GPU memory
        ga, gp = s.get("gpu_active_gb"), s.get("gpu_peak_gb")
        if ga is not None:
            t.append("gpu ", style=L)
            if gp:
                t.append_text(self._gauge(ga / gp if gp else 0))
            t.append(f" {ga}/{gp}GB  " if gp else f" {ga}GB  ", style=C)
        if s.get("tps"):
            t.append("tok/s ", style=L); t.append(f"{s['tps']}  ", style=C)
        t.append("Σ ", style=L)
        t.append(f"{self.tok_in // 1000}k↑ {self.tok_out // 1000}k↓  ", style="#c792ea")
        # system metrics (optional psutil)
        if psutil is None:
            t.append("(uv add psutil for cpu/ram/io)", style="#555555")
            return t
        try:
            cpu = psutil.cpu_percent()
            t.append("cpu ", style=L); t.append_text(self._gauge(cpu / 100)); t.append(f" {cpu:.0f}%  ", style=V)
            vm = psutil.virtual_memory()
            t.append("ram ", style=L); t.append_text(self._gauge(vm.percent / 100))
            t.append(f" {self._fmt_bytes(vm.used)}/{self._fmt_bytes(vm.total)}  ", style=V)
            d, n, now = psutil.disk_io_counters(), psutil.net_io_counters(), time.time()
            dtot = (d.read_bytes + d.write_bytes) if d else 0
            ntot = (n.bytes_sent + n.bytes_recv) if n else 0
            if self._io_prev:
                pd, pn, pt = self._io_prev
                dt = max(0.1, now - pt)
                t.append("disk ", style=L); t.append(f"{self._fmt_bytes((dtot - pd) / dt)}/s  ", style="#8a8a8a")
                t.append("net ", style=L); t.append(f"{self._fmt_bytes((ntot - pn) / dt)}/s", style="#8a8a8a")
            self._io_prev = (dtot, ntot, now)
        except Exception:
            pass
        return t

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
            elif text == "/supercharge":
                if self.busy:
                    self.body_write(Text("[/supercharge: wait until the agent is idle]", style="yellow"))
                else:
                    self.msg_q.put("\x00supercharge")
                return
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
            elif text == "/fx" or text.startswith("/fx "):
                arg = text[len("/fx"):].strip().lower()
                fx = self.query_one("#fx")
                if arg in ("", "toggle"):
                    fx.display = not fx.display
                    msg = f"fx {'on' if fx.display else 'off'}"
                elif arg == "on":
                    fx.display = True; msg = "fx on"
                elif arg == "off":
                    fx.display = False; msg = "fx off"
                elif arg in ("auto", "reset"):
                    fx._pin = None; fx.display = True; msg = "fx auto (reacts to state)"
                elif arg in ("list", "?"):
                    msg = "fx: " + ", ".join(FxBar.EFFECTS) + " · auto · on · off"
                elif arg in FxBar.EFFECTS:
                    fx._pin = arg; fx.display = True; msg = f"fx pinned: {arg}  (/fx auto to unpin)"
                else:
                    msg = f"unknown fx {arg!r} — try /fx list"
                self.body_write(Text(msg, style="yellow"))
                return
            elif text == "/theme" or text.startswith("/theme "):
                fx = self.query_one("#fx")
                fx.display = True
                self.body_write(Text(fx.set_theme(text[len("/theme"):]), style="yellow"))
                return
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
            elif text == "/stats":
                panel = self.query_one("#topstats")
                panel.display = not panel.display
                self.stats_on = panel.display
                self.body_write(Text(f"stats panel {'on' if panel.display else 'off'}", style="yellow"))
                return
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
                        "/subagent <n>  /status  /compact  /supercharge  /model  /fx  /theme  "
                        "/stop (Esc)  /pause (^P) · exit",
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
                if task == "\x00supercharge":
                    core.supercharge(self.client, self.io, self.model, self.workdir,
                                     max_tokens=self.max_tokens)
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
                conn, conn_style, work, mode = "○ offline", "#ff5f5f", "server unreachable", "offline"
            elif s.get("active") and s.get("phase") == "prefill":
                conn = "◓ prefill" if not stale else "◓ prefill ⚠"
                conn_style = "#ffa657" if not stale else "#ff5f5f"  # amber, red if pings stalled
                work = (f"{s.get('processed', 0)}/{s.get('total', '?')} tok "
                        f"(cache {s.get('cached', 0)}) · {s.get('elapsed', 0):.0f}s{ping}")
                mode = "prefill"
            elif s.get("active"):
                conn = "◉ streaming" if not stale else "◉ streaming ⚠"
                conn_style = "#39d3e8" if not stale else "#ff5f5f"  # cyan, red if pings stalled
                work = (f"{s.get('generated', 0)} tok @ {s.get('tps', 0)} tok/s "
                        f"· {s.get('elapsed', 0):.0f}s{ping}")
                mode = "generating"
            elif self.busy:
                conn, conn_style, work, mode = "◌ tools", "#c792ea", "running tools", "tools"  # violet
            else:
                conn, conn_style, work, mode = "● live", "#3fb950", "idle", "idle"  # green
            self.fx_mode = mode  # drive the ambient FxBar animation by current state
            self.fx_stats = {"tps": s.get("tps"), "processed": s.get("processed"),
                             "total": s.get("total"), "ping_age": age}
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
                if self.stats_on:
                    self.call_from_thread(
                        lambda txt=self._stats_line(s): self.query_one("#topstats", Static).update(txt))
            except Exception:
                return
            time.sleep(1.0)
