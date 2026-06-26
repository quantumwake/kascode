"""Composer modal: multiline paste / Ctrl+O expand, send, and draft-preserve.

Drives the REAL widget tree via Textual's run_test (no server; dead port). Sends
are checked with the agent marked busy so they land in steer_q — which nothing
drains without an active turn — instead of msg_q, which the agent-loop thread
would consume out from under the assertion. The idle -> msg_q path is covered by
test_commands (both go through CommandHandler._submit_message).

Run:  uv run python tests/test_composer.py
"""

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import anthropic
from textual.widgets import TextArea

from agent.tui import AgentApp
from agent.tui.widgets import Composer


async def _t() -> None:
    client = anthropic.Anthropic(base_url="http://127.0.0.1:9", api_key="local", max_retries=0)
    app = AgentApp(
        client=client,
        model="m",
        base_url="http://127.0.0.1:9",
        workdir=pathlib.Path(tempfile.mkdtemp()),
        yolo=False,
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        app.busy = True  # route every send to steer_q (deterministic; not drained)

        # --- Ctrl+O opens the composer over the current input line ---
        app.query_one("#input").value = "draft start"
        await pilot.press("ctrl+o")
        await pilot.pause(0.1)
        assert isinstance(app.screen, Composer), "Ctrl+O should open the Composer"
        ta = app.screen.query_one(TextArea)
        assert ta.text == "draft start", ta.text
        assert app.query_one("#input").value == "", "input moves into the composer"

        # edit to multiline + Ctrl+S sends the WHOLE thing (newlines preserved)
        ta.text = "draft start\nsecond line\nthird"
        await pilot.press("ctrl+s")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, Composer), "Ctrl+S closes the composer"
        assert app.io.steer_q.get_nowait() == "draft start\nsecond line\nthird"
        print("Ctrl+O compose + Ctrl+S send (multiline preserved): OK")

        # --- a multiline paste auto-opens the composer pre-filled with it ---
        app.action_compose("alpha\nbeta\ngamma")  # what Ctrl+O does (manual compose)
        await pilot.pause(0.1)
        assert isinstance(app.screen, Composer)
        assert app.screen.query_one(TextArea).text == "alpha\nbeta\ngamma"
        print("multiline paste -> composer opens with full text: OK")

        # --- Esc keeps the text as a draft (no work lost), composer closes ---
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, Composer)
        assert app._pastes == ["alpha\nbeta\ngamma"], app._pastes
        print("Esc keeps the draft (re-staged): OK")

        # --- Ctrl+O pulls the draft back into a fresh composer ---
        await pilot.press("ctrl+o")
        await pilot.pause(0.1)
        assert app.screen.query_one(TextArea).text == "alpha\nbeta\ngamma"
        assert app._pastes == [], "draft pulled into the composer"
        await pilot.press("ctrl+s")
        await pilot.pause(0.1)
        assert app.io.steer_q.get_nowait() == "alpha\nbeta\ngamma"
        print("reopen draft + send: OK")


asyncio.run(_t())
print("all composer tests passed")
