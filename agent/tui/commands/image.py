"""/image [<path>] — attach an image to the next message (by reference).

With a path, stages that file. With no argument, grabs the current clipboard
image on macOS via `pngpaste` (brew install pngpaste). Images are sent to the
(local) server by path, so even a huge screenshot never gets base64'd onto the
wire — set KAS_IMAGE_INLINE=1 only when the server is on another host.
"""

import pathlib
import shutil
import subprocess

from rich.text import Text

from .base import Command

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic")


class ImageCommand(Command):
    name = "/image"
    summary = "attach an image to the next message (path, or clipboard on macOS)"
    usage = "[<path>|install]"
    subcommands = (("install", "install mlx-vlm for image→text (vision models)"),)

    def run(self, app, arg: str) -> None:
        arg = arg.strip()
        if arg.lower() == "install":
            from ._install import install_capability

            install_capability(app, "vision")
            return
        path = self._from_clipboard(app) if not arg else pathlib.Path(arg).expanduser()
        if path is None:
            return
        if not path.is_file():
            app.body_write(Text(f"no such file: {path}", style="red"))
            return
        if path.suffix.lower() not in IMAGE_EXTS:
            app.body_write(Text(f"not an image ({path.suffix}): {path}", style="yellow"))
            return
        app._pending_images.append(str(path.resolve()))
        app.body_write(Text(f"📎 attached {path.name} — sent with your next message", style="cyan"))

    @staticmethod
    def _from_clipboard(app) -> pathlib.Path | None:
        if shutil.which("pngpaste") is None:
            app.body_write(
                Text(
                    "clipboard image needs pngpaste (brew install pngpaste); "
                    "or `/image <path>`, or just drag a file onto the terminal",
                    style="yellow",
                )
            )
            return None
        out = pathlib.Path(app.runner.workdir) / ".agent" / "pastes"
        out.mkdir(parents=True, exist_ok=True)
        dest = out / f"clip-{len(app._pending_images)}-{abs(hash(str(out))) % 10000}.png"
        proc = subprocess.run(["pngpaste", str(dest)], capture_output=True, text=True)
        if proc.returncode != 0 or not dest.exists():
            app.body_write(Text("no image in the clipboard", style="yellow"))
            return None
        return dest
