"""Token-level visualization: turn a per-token logprob summary into renderable
signals — a confidence COLOUR (heatmap over the streamed text), a top-k
"deliberation" panel (the candidates the model weighed), and an ENTROPY level for
the fx bar (how unsure it was each step).

Pure functions + a small VizModes toggle holder. The per-token data ('_viz':
{conf, entropy, top: [[token, prob], ...]}) rides on each text_delta from the
server and is gated behind /viz, so the cost (top-k + entropy over the vocab) is
only paid when a viz mode is on. The server emits it (MLX logprobs); these helpers
just render it.
"""

from dataclasses import dataclass

# Confidence -> colour ramp: peaked/sure (green) -> amber -> coin-flip (red).
_GREEN, _AMBER, _RED, _DIM = "#3fb950", "#ffa657", "#ff5f5f", "#8a8a8a"


def confidence_color(conf: float) -> str:
    """The chosen token's probability -> a heatmap colour."""
    conf = max(0.0, min(1.0, conf))
    if conf >= 0.66:
        return _GREEN
    if conf >= 0.33:
        return _AMBER
    return _RED


def entropy_level(entropy: float, scale: float = 4.0) -> float:
    """Normalise entropy (nats) to 0..1 for the fx bar: 0 = certain, 1 = maximally
    unsure. `scale` nats maps to 1.0 (~4 nats is already very flat in practice)."""
    if scale <= 0:
        return 0.0
    return max(0.0, min(1.0, entropy / scale))


def _show(tok: str) -> str:
    return tok.replace("\n", "⏎").replace("\t", "⇥").replace(" ", "·")[:12]


def topk_lines(top: list, chosen: str | None = None, width: int = 12) -> list[tuple[str, str]]:
    """A compact bar chart of the candidate tokens this step (the 'deliberation').
    Returns (text, style) rows; bars are relative to the top candidate."""
    if not top:
        return []
    rows: list[tuple[str, str]] = [("  the model weighed:", "dim")]
    peak = top[0][1] or 1.0
    for tok, p in top[:6]:
        bars = "█" * max(0, round((p / peak) * width)) if peak else ""
        mark = "→" if chosen is not None and tok == chosen else " "
        rows.append((f"  {mark} {_show(tok):<12} {p:5.2f} {bars}", confidence_color(p)))
    return rows


@dataclass
class VizModes:
    """Which /viz overlays are active (toggled independently)."""

    heatmap: bool = False  # colour streamed tokens by confidence
    topk: bool = False  # show the top-k deliberation panel
    entropy: bool = False  # drive the fx bar from per-token entropy

    @property
    def any_on(self) -> bool:
        return self.heatmap or self.topk or self.entropy

    def header(self) -> str:
        """The value for the x-agent-viz request header (which signals the server
        to compute logprobs). Empty when everything is off."""
        return ",".join(m for m in ("heatmap", "topk", "entropy") if getattr(self, m))

    def summary(self) -> str:
        on = [m for m in ("heatmap", "topk", "entropy") if getattr(self, m)]
        return "viz: " + (" + ".join(on) if on else "off")
