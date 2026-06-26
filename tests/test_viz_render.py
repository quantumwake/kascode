"""/viz rendering wiring: the docked top-k/entropy panel shows/hides + renders
rows, through the real widget tree. (The per-token heatmap colouring in
TuiIO._heat is exercised live; the pure colour/format helpers are in test_viz.)

Run:  uv run python tests/test_viz_render.py
"""

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import anthropic

from agent.tui import AgentApp


async def _t() -> None:
    app = AgentApp(
        client=anthropic.Anthropic(base_url="http://127.0.0.1:9", api_key="x", max_retries=0),
        model="m",
        base_url="http://127.0.0.1:9",
        workdir=pathlib.Path(tempfile.mkdtemp()),
        yolo=False,
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        panel = app.query_one("#vizpanel")
        assert panel.display is False, "viz panel hidden by default"

        app.update_viz_panel(
            [
                ("  entropy 0.50 nats", "dim"),
                ("  the model weighed:", "dim"),
                ("  → mat    0.62 ████████", "#3fb950"),
                ("    floor  0.21 ███", "#ffa657"),
            ]
        )
        assert panel.display is True, "update shows the panel"
        # the rendered content carries the rows (Static renders the Text we set)
        out = app.query_one("#vizpanel").render()
        text = out.plain if hasattr(out, "plain") else str(out)
        assert "entropy" in text and "weighed" in text and "mat" in text
        print("update_viz_panel shows + renders rows: OK")

        app.hide_viz_panel()
        assert panel.display is False, "hide collapses the panel"
        print("hide_viz_panel: OK")

        # /viz off hides the panel; /viz topk leaves it managed by streaming
        app.query_one("#input").value = "/viz off"
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert app.query_one("#vizpanel").display is False
        assert not app.viz.any_on
        print("/viz off hides panel + clears modes: OK")


asyncio.run(_t())
print("all viz-render tests passed")
