"""Tab-completion of /commands through the REAL Input widget (Textual run_test).

Verifies Tab beats focus-navigation and drives the shell-style completion:
extend to the shared prefix, trail a space when a subcommand follows, and list
options at a branch point. No server (dead port); worker threads are daemons.

Run:  uv run python tests/test_tab_complete.py
"""

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import anthropic

from agent.tui import AgentApp


async def _t() -> None:
    client = anthropic.Anthropic(base_url="http://127.0.0.1:9", api_key="local", max_retries=0)
    app = AgentApp(
        client=client,
        model="m",
        base_url="http://127.0.0.1:9",
        workdir=pathlib.Path(tempfile.mkdtemp()),
        yolo=False,
    )
    inp = None

    async def tab(value: str) -> str:
        inp.value = value
        inp.cursor_position = len(value)
        await pilot.press("tab")
        await pilot.pause(0.05)
        return inp.value

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        inp = app.query_one("#input")

        # unique prefix completes fully, no trailing space (takes no arg)
        assert await tab("/comp") == "/compact", inp.value
        print("unique prefix -> full completion: OK")

        # shared prefix among many: extend + trail a space (a subcommand follows)
        assert await tab("/ai") == "/ai-wellbeing ", inp.value
        # next Tab walks into the subcommand
        assert await tab("/ai-wellbeing ") == "/ai-wellbeing chart ", inp.value
        print("shared prefix + subcommand chaining: OK")

        # a command that takes args trails a space so you can type the arg
        assert await tab("/rag") == "/rag ", inp.value
        # at the branch point (/rag enable | /rag disable) Tab lists, leaves value
        before = inp.value
        body_lines_before = len(app.query_one("#body").lines)
        out = await tab("/rag ")
        assert out == before, "listing options must not change the input"
        assert len(app.query_one("#body").lines) > body_lines_before, "options were listed"
        print("branch point lists options: OK")

        # a non-command line: Tab is a no-op for completion (focus nav untouched)
        inp.value = "hello"
        inp.cursor_position = 5
        await pilot.press("tab")
        await pilot.pause(0.05)
        assert inp.value == "hello"
        print("non-command Tab left alone: OK")


asyncio.run(_t())
print("all tab-complete tests passed")
