"""Tests for the compaction policy: the hard/soft classifier (which decides
what may fire mid-tool-call vs what defers to a turn boundary) and the /ctx
command. No model/server needed.

Run:  uv run python tests/test_compaction.py
"""

import sys
from collections import deque

sys.path.insert(0, ".")

from agent import config
from agent.core.compaction import classify_compaction, ctx_command


class FakeRunner:
    def __init__(self, **kw):
        self.context_limit = kw.get("context_limit", 100_000)
        self.compact_cooldown = kw.get("compact_cooldown", 0)
        self.compact_floor = kw.get("compact_floor", 0)
        self.tps_window = deque(kw.get("tps_window", []), maxlen=4)
        self.tps_valve = kw.get("tps_valve", True)
        self.hard_limit_frac = kw.get("hard_limit_frac", 0.85)
        self.compact_at = kw.get("compact_at", config.COMPACT_AT)
        self.last_input_tokens = kw.get("last_input_tokens", 0)


# ---------------------------------------------------------------------------
# classify_compaction
# ---------------------------------------------------------------------------

# Hard overflow: past 0.85 * context_limit -> "hard", even with cooldown active.
r = FakeRunner(context_limit=100_000, compact_cooldown=5)
level, _ = classify_compaction(r, 90_000, compact_at=200_000)
assert level == "hard", level

# Below the hard limit, cooldown suppresses soft triggers.
r = FakeRunner(context_limit=100_000, compact_cooldown=3, tps_window=[1.0, 1.0])
assert classify_compaction(r, 10_000, 5_000)[0] == "none"

# Decode-speed valve: smoothed tps below COMPACT_TPS over >=2 samples -> soft.
slow = [config.COMPACT_TPS - 2] * 2
r = FakeRunner(context_limit=100_000, tps_window=slow)
assert classify_compaction(r, 10_000, compact_at=0)[0] == "soft"

# ...but only when the valve is on.
r = FakeRunner(context_limit=100_000, tps_window=slow, tps_valve=False)
assert classify_compaction(r, 10_000, compact_at=0)[0] == "none"

# Size cap: grown past compact_at over the floor -> soft.
r = FakeRunner(context_limit=1_000_000, compact_floor=1_000, tps_window=[99, 99])
assert classify_compaction(r, 60_000, compact_at=50_000)[0] == "soft"
# ...and compact_at=0 disables the size trigger.
assert classify_compaction(r, 60_000, compact_at=0)[0] == "none"

# Plenty of room, fast decode -> nothing.
r = FakeRunner(context_limit=100_000, tps_window=[99, 99])
assert classify_compaction(r, 5_000, compact_at=50_000)[0] == "none"
print("classify_compaction: OK")


# ---------------------------------------------------------------------------
# ctx_command
# ---------------------------------------------------------------------------

# /ctx max -> ride to the hard limit: size cap off + decode valve off.
r = FakeRunner(context_limit=262_000, last_input_tokens=48_000)
out = ctx_command(r, "max")
assert r.compact_at == 0 and r.tps_valve is False, (r.compact_at, r.tps_valve)
assert "decode-valve off" in out, out

# /ctx auto -> restore defaults.
out = ctx_command(r, "auto")
assert r.compact_at == config.COMPACT_AT and r.tps_valve is True

# numeric target, clamped to the hard limit (0.85 * 262k ~= 222k).
ctx_command(r, "500000")
assert r.compact_at == int(0.85 * 262_000), r.compact_at
# a sane value passes through; "k" suffix supported.
ctx_command(r, "120k")
assert r.compact_at == 120_000, r.compact_at

# valve toggles.
ctx_command(r, "valve off")
assert r.tps_valve is False
ctx_command(r, "valve on")
assert r.tps_valve is True

# bad input is reported, not crashed, and leaves state intact.
before = r.compact_at
out = ctx_command(r, "banana")
assert "usage:" in out and r.compact_at == before, out

# status line shape (no-arg query).
out = ctx_command(r, "")
assert "window" in out and "using" in out and "hard limit" in out, out
print("ctx_command: OK")

print("all compaction tests passed")
