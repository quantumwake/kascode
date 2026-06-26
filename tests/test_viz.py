"""/viz token visualization: the pure rendering helpers (confidence colour ramp,
entropy normalisation, top-k deliberation panel) and the VizModes toggle +
command. No model/server — renders from synthetic per-token logprob summaries.

Run:  uv run python tests/test_viz.py
"""

import queue
import sys

sys.path.insert(0, ".")

from agent.tui.commands import REGISTRY
from agent.tui.commands.viz import VizCommand
from agent.tui.viz import VizModes, confidence_color, entropy_level, topk_lines

# --- confidence colour ramp (heatmap) --------------------------------------
assert confidence_color(0.95) == "#3fb950"  # sure -> green
assert confidence_color(0.5) == "#ffa657"  # middling -> amber
assert confidence_color(0.05) == "#ff5f5f"  # coin-flip -> red
assert confidence_color(2.0) == confidence_color(1.0)  # clamped
print("confidence colour ramp: OK")

# --- entropy normalisation (fx level) --------------------------------------
assert entropy_level(0.0) == 0.0
assert entropy_level(4.0) == 1.0 and entropy_level(9.0) == 1.0  # clamped at scale
assert 0.0 < entropy_level(1.0) < 1.0
print("entropy level: OK")

# --- top-k deliberation panel ----------------------------------------------
assert topk_lines([]) == []
rows = topk_lines([["mat", 0.62], ["floor", 0.21], ["rug", 0.09]], chosen="mat")
text = "\n".join(t for t, _ in rows)
assert "weighed" in rows[0][0]
assert "mat" in text and "floor" in text and "0.62" in text
assert any("→" in t for t, _ in rows), "the chosen token is marked"
assert any("·" in t for t, _ in topk_lines([[" the", 0.4]])), "space rendered visibly"
print("top-k panel: OK")

# --- VizModes toggles + request header -------------------------------------
m = VizModes()
assert not m.any_on and m.header() == "" and m.summary() == "viz: off"
m.heatmap = True
m.entropy = True
assert m.any_on and m.header() == "heatmap,entropy"
assert m.summary() == "viz: heatmap + entropy"
print("VizModes header/summary: OK")


# --- /viz command toggles app.viz ------------------------------------------
class FakeApp:
    def __init__(self):
        self.viz = VizModes()
        self.writes: list[str] = []
        self.msg_q: queue.Queue = queue.Queue()

    def body_write(self, r):
        self.writes.append(str(r))


cmd = next(c for c in REGISTRY if c.name == "/viz")
assert isinstance(cmd, VizCommand)
app = FakeApp()
cmd.run(app, "heatmap")
assert app.viz.heatmap and not app.viz.topk
cmd.run(app, "heatmap")  # independent toggle off
assert not app.viz.heatmap
cmd.run(app, "all")
assert app.viz.heatmap and app.viz.topk and app.viz.entropy
cmd.run(app, "off")
assert not app.viz.any_on
assert cmd.completions()[0] == "/viz" and "/viz topk" in cmd.completions()
print("/viz command toggles + completions: OK")

print("all viz tests passed")
