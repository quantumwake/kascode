"""Shared `<command> install` helper — runs a capability's pip install off the
UI thread and reports, mirroring how `/memory install` works. Lets each gated
modality feature (/listen, /image, /say, /show) offer a one-word install."""

import importlib
import subprocess
import threading

from rich.text import Text


def install_capability(app, cap_id: str) -> None:
    """Install the Python packages for doctor capability `cap_id`, then tell the
    user to retry the command (a restart may be needed for a fresh import)."""
    from scripts.doctor import capability_install_command

    cmd, note = capability_install_command(cap_id)
    if cmd is None:
        app.body_write(Text(f"can't install: {note}", style="yellow"))
        return
    app.body_write(Text(f"[installing: {' '.join(cmd)}{note} …]", style="yellow"))

    def work() -> None:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            for line in (proc.stdout + proc.stderr).strip().splitlines()[-4:]:
                app.call_from_thread(app.body_write, Text(f"  {line}", style="dim"))
            if proc.returncode == 0:
                importlib.invalidate_caches()  # so find_spec sees the new package
                app.call_from_thread(
                    app.body_write,
                    Text(
                        "[installed — try the command again "
                        "(restart kas if it doesn't light up)]",
                        style="green",
                    ),
                )
            else:
                app.call_from_thread(
                    app.body_write, Text("[install failed — see above]", style="red")
                )
        except Exception as exc:
            app.call_from_thread(
                app.body_write, Text(f"[install error: {type(exc).__name__}: {exc}]", style="red")
            )

    threading.Thread(target=work, daemon=True).start()
