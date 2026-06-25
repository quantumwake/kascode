"""Sticky-tail scrolling for the main output (so it stays selectable).

Regression: the body RichLog used plain auto_scroll, which yanked the view to the
bottom on EVERY write. Once you scrolled up to read or select earlier output, any
streamed token/notice jumped you away — making the main area impossible to select
while anything was being written. body_write now follows the tail only when
already at the bottom.

Run:  uv run python tests/test_body_scroll.py
"""

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import anthropic

from agent.tui import AgentApp
from agent.tui.widgets import SelectableRichLog


async def _t() -> None:
    app = AgentApp(
        client=anthropic.Anthropic(base_url="http://127.0.0.1:9", api_key="x", max_retries=0),
        model="m",
        base_url="http://127.0.0.1:9",
        workdir=pathlib.Path(tempfile.mkdtemp()),
        yolo=False,
        mouse_select=True,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.3)
        body = app.query_one("#body")
        assert isinstance(body, SelectableRichLog) and body.allow_select
        assert body.can_focus is False, "body must not steal focus from the input"

        for i in range(60):  # overflow so there's somewhere to scroll
            app.body_write(f"line {i:02d} selectable output")
        await pilot.pause(0.05)

        # at the bottom: new output keeps following (tail -f)
        app.body_write("newest line")
        await pilot.pause(0.02)
        assert body.scroll_offset.y == body.max_scroll_y, "at bottom -> keeps tailing"

        # scrolled up: a new write must NOT yank the view back down
        body.scroll_to(y=10, animate=False)
        await pilot.pause(0.05)
        app.body_write("a line arrives while you're scrolled up")
        await pilot.pause(0.05)
        assert body.scroll_offset.y == 10, f"scrolled up must stay put, got {body.scroll_offset.y}"

        # a selection survives writes that land while scrolled up, AND is actually
        # painted (the real bug: stock RichLog.render_line never applied the
        # selection style, so the highlight was invisible even though the state
        # was correct). Drag across rows, then check the selection bg is rendered.
        await pilot.mouse_down(body, offset=(4, 1))
        await pilot.hover(body, offset=(20, 3))
        app.body_write("write during selection")
        await pilot.pause(0.05)
        assert body.scroll_offset.y == 10 and app.screen._selecting
        sel_bg = str(app.screen.get_component_rich_style("screen--selection").bgcolor)
        painted = 0
        for vy in range(body.size.height):
            strip = body.render_line(vy)
            painted += sum(
                seg.cell_length
                for seg in strip
                if seg.style and seg.style.bgcolor and str(seg.style.bgcolor) == sel_bg
            )
        assert painted > 0, "selection highlight must be painted into the body strips"
        await pilot.mouse_up(body, offset=(20, 3))
        # clicking the body to select keeps the input focused
        assert type(app.focused).__name__ == "PasteInput"


asyncio.run(_t())
print("sticky-tail body scroll + stays selectable: OK")
