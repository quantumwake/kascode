"""Terminal image preview: half-block render, iTerm2 inline escape, and the
/show command. Uses a tiny in-memory PNG so no real image/model is needed.

Run:  uv run python tests/test_image_preview.py
"""

import importlib.util
import pathlib
import sys
import tempfile
import types

sys.path.insert(0, ".")

if importlib.util.find_spec("PIL") is None:  # Pillow is the optional 'preview' extra
    print("test_image_preview: skipped (Pillow not installed — pip install pillow / extra [preview])")
    sys.exit(0)

from PIL import Image

from agent.tui.commands.show import ShowCommand
from agent.tui.image_preview import (
    halfblock_text,
    iterm_inline,
    open_command,
    pillow_available,
    supports_iterm,
)


def make_png(w=16, h=16) -> pathlib.Path:
    img = Image.new("RGB", (w, h))
    for y in range(h):
        for x in range(w):
            img.putpixel((x, y), (220, 40, 40) if y < h // 2 else (40, 40, 220))
    p = pathlib.Path(tempfile.mktemp(suffix=".png"))
    img.save(p)
    return p


png = make_png(16, 16)

# half-block: cols clamped to max_cols, rows = cols*aspect/2, every cell colored.
t = halfblock_text(png, max_cols=8)
lines = t.plain.split("\n")
assert len(lines) == 4, lines  # 16x16 -> 8 cols -> 4 half-block rows (8 px tall)
assert all(len(line) == 8 for line in lines), [len(x) for x in lines]
assert all("▀" in line for line in lines)
assert len(t.spans) == 8 * 4  # one colored span per cell
print("halfblock_text: OK")

# iTerm2 inline escape framing.
seq = iterm_inline(png, max_cols=8)
assert seq.startswith("\033]1337;File=inline=1;") and seq.endswith("\a")
assert pillow_available() is True
assert isinstance(supports_iterm(), bool)
print("iterm_inline: OK")

# open_command is platform-appropriate (or None on unknown OS).
cmd = open_command(png)
assert cmd is None or cmd[0] in ("open", "xdg-open")
print("open_command: OK")


# /show command: inline render writes a renderable; missing file warns; no crash.
class StubApp:
    def __init__(self, workdir):
        self.runner = types.SimpleNamespace(workdir=workdir)
        self.writes = []

    def body_write(self, r):
        self.writes.append(r)


cmd = ShowCommand()
app = StubApp(workdir=str(png.parent))
cmd.run(app, png.name)  # relative to workdir
assert app.writes and hasattr(app.writes[-1], "plain"), app.writes  # a Rich Text
assert "▀" in app.writes[-1].plain

app = StubApp(workdir=str(png.parent))
cmd.run(app, "")
assert "usage:" in str(app.writes[-1])

app = StubApp(workdir=str(png.parent))
cmd.run(app, "nope-does-not-exist.png")
assert "no such file" in str(app.writes[-1])
print("/show command: OK")

print("all image-preview tests passed")
