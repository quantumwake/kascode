"""/show <path> — preview an image inline (half-block), or `open` it externally."""

import pathlib
import subprocess

from rich.text import Text

from ..image_preview import halfblock_text, open_command, pillow_available
from .base import Command


class ShowCommand(Command):
    name = "/show"
    summary = "preview an image inline (half-block render) or open it externally"
    usage = "<path> [open]"

    def run(self, app, arg: str) -> None:
        parts = arg.strip().split()
        if not parts:
            app.body_write(Text("usage: /show <path> [open]", style="yellow"))
            return
        external = parts[-1] == "open"
        rel = " ".join(parts[:-1] if external else parts)
        path = pathlib.Path(rel)
        if not path.is_absolute():
            path = pathlib.Path(app.runner.workdir) / path
        if not path.exists():
            app.body_write(Text(f"no such file: {path}", style="red"))
            return

        if external:
            cmd = open_command(path)
            if cmd is None:
                app.body_write(Text(f"can't open files on this OS: {path}", style="red"))
                return
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            app.body_write(Text(f"[opened {path} in the system viewer]", style="cyan"))
            return

        if not pillow_available():
            app.body_write(
                Text(
                    f"inline preview needs Pillow (uv add pillow); try `/show {rel} open`. "
                    f"file: {path}",
                    style="yellow",
                )
            )
            return
        try:
            app.body_write(halfblock_text(path, max_cols=72))
        except Exception as exc:  # decode/format errors shouldn't crash the TUI
            app.body_write(Text(f"could not render {path}: {exc}", style="red"))
