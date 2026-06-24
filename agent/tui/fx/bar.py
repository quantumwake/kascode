"""FxBar — the one-row ambient CRT animation widget.

Holds the palette/effect state machine (_tick) and theme control (set_theme);
the per-frame renderers live in the FxEffects mixin (effects.py). The bar reacts
to app.fx_mode (idle / prefill / generating / tools / offline).
"""

import random

from textual.widgets import Static

from .effects import FxEffects


class FxBar(FxEffects, Static):
    """A one-row ambient CRT animation strip that REACTS to what the agent is
    doing — the palette and effect track the app's fx_mode (idle / prefill /
    generating / tools / offline). Toggle with /fx. One line, so it's cheap.

      idle       amber twinkle (calm)
      prefill    orange breathing pulse (warming up)
      generating cyan equalizer wave, faster (tokens flowing)
      tools      violet comet sweep (working)
      offline    dim red flatline
    """

    # palette per state, dim → bright (last entry matches the status-line colour)
    PALETTES = {
        "idle": ["#3a2000", "#7a4500", "#b86800", "#ffb000", "#ffd470"],  # amber
        "prefill": ["#3a1e00", "#7a3d00", "#b85c00", "#ffa657", "#ffd0a0"],  # orange
        "generating": ["#06363b", "#0a6b74", "#1aa6b3", "#39d3e8", "#9af2ff"],  # cyan
        "tools": ["#2a1640", "#4f2d80", "#7a45c0", "#c792ea", "#e9d4ff"],  # violet
        "offline": ["#2a0000", "#5a0d0d", "#8a1f1f", "#ff5f5f", "#ffb0b0"],  # red
    }
    # Colour schemes the rotating states cycle through. Most are MULTI-HUE mixes
    # (red/orange/yellow/green/blue/white together) so the bar bursts with colour,
    # plus a few mono ramps for contrast.
    PALETTE_POOL = [
        [
            "#ff3b30",
            "#ff9500",
            "#ffcc00",
            "#34c759",
            "#0a84ff",
        ],  # rgb (red→orange→yellow→green→blue)
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
        "idle": (
            "twinkle",
            "pulse",
            "plasma",
            "starfield",
            "fire",
            "heartbeat",
            "bounce",
            "dna",
            "ripple",
            "rain",
            "sine",
            "lava",
            "aurora",
            "throb",
            "glimmer",
            "confetti",
            "noise",
            "firefly",
        ),
        "prefill": ("progress",),
        "generating": (
            "wave",
            "vu",
            "spectrum",
            "zigzag",
            "scanline",
            "ladder",
            "rotor",
            "braille",
            "fireworks",
            "symbars",
        ),
        "tools": (
            "comet",
            "larson",
            "snake",
            "marquee",
            "binary",
            "glitch",
            "wipe",
            "morse",
            "worm",
            "crossing",
            "parallax",
            "wavefront",
            "meteor",
        ),
        "offline": ("flat",),
    }
    # Per-mode animation speed (float step added to self._t each tick). idle drifts
    # gently; working states race so the difference reads at a glance.
    MODE_SPEED = {"idle": 0.5, "prefill": 1.0, "generating": 2.0, "tools": 1.6, "offline": 0.4}
    # Named colour themes for `/theme <name>` — pins the whole bar to one palette
    # (overrides idle's rotation + the working signature). `/theme auto` clears it.
    THEMES = {
        "matrix": ["#06340a", "#0a7a1a", "#1aa82a", "#39e85a", "#9affb0"],
        "amber": ["#3a2000", "#7a4500", "#b86800", "#ffb000", "#ffd470"],
        "ice": ["#0a2a4a", "#155a8a", "#2a8ac8", "#4ec3f0", "#a8e8ff"],
        "fire": ["#c81d11", "#ff5e00", "#ffae00", "#ffe600", "#ffffff"],
        "neon": ["#ff2d95", "#feec00", "#00f5d4", "#00bbf9", "#9b5de5"],
        "synthwave": ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff"],
        "rainbow": ["#ff0040", "#ff8c00", "#ffe600", "#00d26a", "#3a86ff"],
        "purple": ["#1a0a3a", "#3d1d7a", "#6a2dc0", "#a05cf0", "#d4b0ff"],
        "mono": ["#222222", "#555555", "#888888", "#bbbbbb", "#ffffff"],
    }
    # effects a user can pin via `/fx <name>`
    EFFECTS = (
        "twinkle",
        "pulse",
        "wave",
        "comet",
        "plasma",
        "scanline",
        "fire",
        "starfield",
        "braille",
        "progress",
        "heartbeat",
        "flat",
        "larson",
        "bounce",
        "vu",
        "dna",
        "ripple",
        "rain",
        "marquee",
        "glitch",
        "sine",
        "meteor",
        "snake",
        "spectrum",
        "wipe",
        "binary",
        "firefly",
        "fireworks",
        "zigzag",
        "throb",
        "morse",
        "lava",
        "worm",
        "aurora",
        "crossing",
        "glimmer",
        "ladder",
        "rotor",
        "parallax",
        "wavefront",
        "symbars",
        "confetti",
        "noise",
    )

    def __init__(self) -> None:
        super().__init__("", id="fx")
        self._t = 0
        self._tf = 0.0  # float clock; per-mode speed advances it (see _tick)
        self._frame = 0  # ticks since mount, for rotation timing
        self._rotate_at = 0  # frame to switch effect on
        self._mode: str | None = None
        self._effect = "twinkle"
        self._cur: str | None = None  # last effect actually rendered (to reset buffers on change)
        self._pin: str | None = None  # forced effect (/fx <name>); None = rotate
        self._palette: list[str] | None = None  # current colour scheme
        self._theme: list[str] | None = None  # /theme override: pins palette for all states
        self._theme_name: str | None = None  # name of the active /theme (None = auto)
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
            return (
                f"themes: {names} · auto — current: "
                f"{self._theme_name or 'auto'} (e.g. /theme matrix)"
            )
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
