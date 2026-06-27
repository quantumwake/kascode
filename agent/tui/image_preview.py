"""Render an image in the terminal.

Two paths, because a full-screen Textual app and a plain console want different
things:

  - halfblock_text(): a Rich Text built from the image's pixels using the upper
    half-block glyph (▀) — fg = top pixel, bg = bottom pixel, so each character
    cell shows two stacked pixels. This is just colored text, so it composes
    natively inside Textual's RichLog (unlike the iTerm2/kitty image protocols,
    which write straight to the terminal and get clobbered by the compositor).
  - iterm_inline(): the iTerm2 inline-image escape, for the non-TUI ConsoleIO
    path or `kas` piping to a real terminal.

Pillow is an optional dep here only for decoding/resizing; callers fall back to
just printing the path (and on macOS, `open`-ing it) when it's missing.
"""

import base64
import os
import pathlib

from rich.text import Text

UPPER = "▀"  # fg painted on top half, bg shows through bottom half


def pillow_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("PIL") is not None


def halfblock_text(path: str | pathlib.Path, max_cols: int = 64) -> Text:
    """Render `path` as a Rich Text of half-block rows, downscaled to max_cols.

    Raises ImportError if Pillow is missing — callers should guard with
    pillow_available() and degrade to a path/open fallback.
    """
    from PIL import Image

    img = Image.open(path).convert("RGB")
    w, h = img.size
    cols = max(1, min(max_cols, w))
    # Each cell is 2 px tall and roughly twice as tall as wide, so the row count
    # is scaled by the aspect ratio without the usual /2 squish.
    rows = max(1, round(cols * h / w / 2))
    img = img.resize((cols, rows * 2))
    px = img.load()

    text = Text(no_wrap=True)
    for row in range(rows):
        for col in range(cols):
            tr, tg, tb = px[col, row * 2]
            br, bb, bg_ = px[col, row * 2 + 1]
            text.append(
                UPPER,
                style=f"#{tr:02x}{tg:02x}{tb:02x} on #{br:02x}{bb:02x}{bg_:02x}",
            )
        if row != rows - 1:
            text.append("\n")
    return text


def supports_iterm() -> bool:
    return os.environ.get("TERM_PROGRAM") == "iTerm.app"


def iterm_inline(path: str | pathlib.Path, max_cols: int = 64) -> str:
    """iTerm2 inline-image escape sequence (full-resolution, for console mode)."""
    data = pathlib.Path(path).read_bytes()
    b64 = base64.b64encode(data).decode()
    return (
        f"\033]1337;File=inline=1;width={max_cols};preserveAspectRatio=1;size={len(data)}:"
        f"{b64}\a"
    )


def open_command(path: str | pathlib.Path) -> list[str] | None:
    """Best command to open `path` in the OS image viewer, or None if unknown."""
    import platform

    sysname = platform.system()
    if sysname == "Darwin":
        return ["open", str(path)]
    if sysname == "Linux":
        return ["xdg-open", str(path)]
    return None
