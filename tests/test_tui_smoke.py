"""Headless smoke test for the decomposed TUI (v3 Phase 3).

Mounts AgentApp via Textual's run_test harness and drives a command through the
REAL widget tree — verifying that compose / on_mount / FxBar / the command
dispatch wire together across the agent/tui/ package, not merely that the
modules import. No server needed: the status loop tolerates an unreachable one
(we point at a dead port). Worker threads are daemons, so the process exits.

Run:  uv run python tests/test_tui_smoke.py
"""

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import anthropic

from agent.tui import AgentApp


async def _smoke() -> None:
    client = anthropic.Anthropic(base_url="http://127.0.0.1:9", api_key="local", max_retries=0)
    app = AgentApp(
        client=client,
        model="m",
        base_url="http://127.0.0.1:9",  # dead port — mount must not depend on a server
        workdir=pathlib.Path(tempfile.mkdtemp()),
        yolo=False,
        theme="matrix",
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)  # mount, compose, one fx tick, one status poll
        # a slash command routed through the real Input widget toggles app state
        app.query_one("#input").value = "/yolo"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.runner.yolo is True, "/yolo via the real TUI should toggle the flag"
        # a widget-backed command (re-themes chrome + fx) runs without error
        app.query_one("#input").value = "/theme fire"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.query_one("#fx") is not None  # fx bar present and rendering


asyncio.run(_smoke())
print("tui smoke: mount + compose + fx + command dispatch OK")
