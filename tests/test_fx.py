"""fx bar control: cycle/set_speed/status units, plus the interactive /fx browse
flow (type /fx, Tab/Space to flip effects live, Enter keeps, Esc cancels) driven
through the real widget tree.

Run:  uv run python tests/test_fx.py
"""

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import anthropic

from agent.tui import AgentApp
from agent.tui.fx import FxBar

E = FxBar.EFFECTS

# --- cycle: wraps, pins, delta=0 keeps current ------------------------------
fx = FxBar()
fx._pin, fx._effect = None, E[0]
assert fx.cycle(1) == E[1] and fx._pin == E[1]
assert fx.cycle(1) == E[2]
assert fx.cycle(-1) == E[1]
fx._pin = E[-1]
assert fx.cycle(1) == E[0], "cycle wraps around"
fx._pin = "pulse"
assert fx.cycle(0) == "pulse", "delta=0 pins the current effect"
print("FxBar.cycle: OK")

# --- set_speed: presets, float, clamp, invalid ------------------------------
assert fx.set_speed("fast").endswith("1.80×") and fx._speed == 1.8
fx.set_speed("0.5")
assert fx._speed == 0.5
fx.set_speed("normal")
assert fx._speed == 1.0
fx.set_speed("99")
assert fx._speed == 5.0, "clamped to 5.0"
assert "use slow" in fx.set_speed("bogus") and fx._speed == 5.0, "invalid keeps speed"
assert "speed" in fx.status() and "effect" in fx.status()
print("FxBar.set_speed + status: OK")


# --- interactive /fx browse via the real TUI --------------------------------
async def _browse() -> None:
    app = AgentApp(
        client=anthropic.Anthropic(base_url="http://127.0.0.1:9", api_key="x", max_retries=0),
        model="m",
        base_url="http://127.0.0.1:9",
        workdir=pathlib.Path(tempfile.mkdtemp()),
        yolo=False,
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        bar = app.query_one("#fx")

        # type /fx -> enters browse mode (pins the current effect)
        app.query_one("#input").value = "/fx"
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert app._fx_browsing is True, "/fx enters browse mode"
        first = bar._pin
        assert first in E

        # Tab / Space flip forward; Shift+Tab flips back
        await pilot.press("tab")
        await pilot.pause(0.02)
        second = bar._pin
        assert second != first and second in E, "Tab advances the effect"
        await pilot.press("space")
        await pilot.pause(0.02)
        assert bar._pin != second, "Space advances too"
        await pilot.press("shift+tab")
        await pilot.pause(0.02)
        assert bar._pin == second, "Shift+Tab goes back"

        # Enter keeps the current effect and exits browse
        kept = bar._pin
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert app._fx_browsing is False and bar._pin == kept, "Enter keeps + exits"

        # browse again, then Esc cancels -> restores the pin we had on entry
        before = bar._pin
        app.query_one("#input").value = "/fx"
        await pilot.press("enter")
        await pilot.pause(0.05)
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.pause(0.02)
        assert bar._pin != before
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert app._fx_browsing is False and bar._pin == before, "Esc cancels + restores"


asyncio.run(_browse())
print("/fx browse (Tab/Space flip · Enter keep · Esc cancel): OK")
print("all fx tests passed")
