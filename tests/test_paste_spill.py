"""Big/multiline paste is spilled to a temp file under .agent/pastes/ and a
compact `[pasted content @ <relpath>]` reference is inserted inline at the cursor
(so the model reads the file instead of the input being flooded). Driven through
the real widget tree.

Run:  uv run python tests/test_paste_spill.py
"""

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import anthropic

from agent.tui import AgentApp


async def _t() -> None:
    workdir = pathlib.Path(tempfile.mkdtemp())
    app = AgentApp(
        client=anthropic.Anthropic(base_url="http://127.0.0.1:9", api_key="x", max_retries=0),
        model="m",
        base_url="http://127.0.0.1:9",
        workdir=workdir,
        yolo=False,
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        inp = app.query_one("#input")

        # type an instruction, place the cursor, then paste a multiline blob
        inp.value = "summarize this: "
        inp.cursor_position = len(inp.value)
        blob = "line one\nline two\nline three with more text\n" * 5
        app.spill_paste_to_file(blob)

        # the input keeps the typed text + a compact inline reference (not the blob)
        assert blob not in inp.value, "the raw blob must NOT flood the input"
        assert "[pasted content @ .agent/pastes/" in inp.value, inp.value
        assert inp.value.startswith("summarize this: [pasted content @ "), inp.value

        # the reference points at a real file containing the full paste
        ref = inp.value.split("@ ", 1)[1].rstrip("]").strip()
        path = workdir / ref
        assert path.exists() and path.read_text() == blob, "spilled file must hold the paste"
        assert path.suffix == ".txt"
        assert ".agent" in path.parts, "spilled under .agent (gitignored)"
        print("multiline paste -> temp file + inline reference: OK")

        # JSON content gets a .json extension
        inp.value, inp.cursor_position = "", 0
        app.spill_paste_to_file('{\n  "a": 1,\n  "b": [2, 3]\n}')
        jref = inp.value.split("@ ", 1)[1].rstrip("]").strip()
        assert (workdir / jref).suffix == ".json", jref
        print("json paste -> .json extension: OK")


asyncio.run(_t())
print("all paste-spill tests passed")
