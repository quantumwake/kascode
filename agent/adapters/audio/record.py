"""Mic capture to a 16 kHz mono WAV via ffmpeg (what Whisper wants).

ffmpeg is the one external dependency; the input device is platform-specific
(avfoundation on macOS, PulseAudio on Linux). KAS_STT_DEVICE overrides the
device spec. Returns (path|None, error) — never raises for an absent recorder.
"""

import os
import pathlib
import platform
import shutil
import subprocess


def record_command(out_path: str | pathlib.Path, seconds: int) -> list[str] | None:
    """ffmpeg argv for a `seconds`-long 16 kHz mono capture, or None if this OS
    has no known input format."""
    sysname = platform.system()
    common_tail = ["-t", str(seconds), "-ar", "16000", "-ac", "1", str(out_path)]
    if sysname == "Darwin":
        device = os.environ.get("KAS_STT_DEVICE", ":0")  # avfoundation "video:audio"
        return ["ffmpeg", "-y", "-f", "avfoundation", "-i", device, *common_tail]
    if sysname == "Linux":
        device = os.environ.get("KAS_STT_DEVICE", "default")
        return ["ffmpeg", "-y", "-f", "pulse", "-i", device, *common_tail]
    return None


def record(out_path: str | pathlib.Path, seconds: int = 5) -> tuple[pathlib.Path | None, str]:
    """Block for `seconds`, capturing the mic to `out_path`. Returns (path, "")
    on success or (None, error_message)."""
    if shutil.which("ffmpeg") is None:
        return None, "recording needs ffmpeg (brew install ffmpeg / apt install ffmpeg)"
    cmd = record_command(out_path, seconds)
    if cmd is None:
        return None, f"mic capture not wired for {platform.system()}"
    try:
        # stdin=DEVNULL: ffmpeg's avfoundation reads no stdin, and giving it a
        # clean fd avoids inheriting the TUI thread's std fds (the same class of
        # issue that breaks subprocess forks from inside Textual).
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=seconds + 20,
        )
    except subprocess.TimeoutExpired:
        return None, "recording timed out"
    out = pathlib.Path(out_path)
    if proc.returncode != 0 or not out.exists():
        tail = (proc.stderr or proc.stdout or "").strip()[-300:]
        return None, f"recording failed (exit {proc.returncode}): {tail}"
    return out, ""
