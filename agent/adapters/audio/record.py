"""Mic capture to a 16 kHz mono WAV via ffmpeg (what Whisper wants).

ffmpeg is the one external dependency; the input device is platform-specific
(avfoundation on macOS, PulseAudio on Linux). KAS_STT_DEVICE overrides the
device spec. Returns (path|None, error) — never raises for an absent recorder.

Two niceties for a good "listening" UX:
  - warmup: avfoundation takes a few hundred ms to start delivering frames, so we
    record a short lead-in and cue the user to speak (on_ready) only after it, so
    the first words aren't truncated into a cold mic. KAS_STT_WARMUP tunes it.
  - level meter: with on_level set we add ffmpeg's `ebur128` filter (audio passes
    through unchanged) and parse its momentary-loudness lines (~10/s) into a 0..1
    level, so the TUI can show a live voice meter.
"""

import os
import pathlib
import platform
import re
import shutil
import subprocess
import threading

_M_RE = re.compile(r"M:\s*(-?\d+(?:\.\d+)?)")  # ebur128 momentary loudness (LUFS)


def record_command(
    out_path: str | pathlib.Path, seconds: float, meter: bool = False
) -> list[str] | None:
    """ffmpeg argv for a `seconds`-long 16 kHz mono capture, or None if this OS
    has no known input format. `meter` adds ebur128 loudness logging to stderr."""
    sysname = platform.system()
    af = ["-af", "ebur128=metadata=1"] if meter else []
    # Force pcm_s16le so Python's `wave` module can always decode it (ffmpeg
    # otherwise sometimes writes WAVE_FORMAT_EXTENSIBLE, which `wave` rejects).
    tail = [*af, "-t", str(seconds), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out_path)]
    if sysname == "Darwin":
        device = os.environ.get("KAS_STT_DEVICE", ":0")  # avfoundation "video:audio"
        return ["ffmpeg", "-y", "-f", "avfoundation", "-i", device, *tail]
    if sysname == "Linux":
        device = os.environ.get("KAS_STT_DEVICE", "default")
        return ["ffmpeg", "-y", "-f", "pulse", "-i", device, *tail]
    return None


def _loudness_to_level(lufs: float) -> float:
    """Map momentary loudness (~-70 silence .. 0 loud) to a 0..1 meter level."""
    return max(0.0, min(1.0, (lufs + 50.0) / 50.0))


def record(
    out_path: str | pathlib.Path, seconds: int = 5, on_ready=None, on_level=None
) -> tuple[pathlib.Path | None, str]:
    """Capture the mic to `out_path`. Returns (path, "") or (None, error).

    on_ready() fires once the mic is hot (after the warmup lead-in); on_level(x)
    fires with x in 0..1 as the user speaks (a live meter). The recording is
    seconds+warmup long so the lead-in doesn't eat into the user's time."""
    if shutil.which("ffmpeg") is None:
        return None, "recording needs ffmpeg (brew install ffmpeg / apt install ffmpeg)"
    warmup = float(os.environ.get("KAS_STT_WARMUP", "0.3"))
    cmd = record_command(out_path, round(seconds + warmup, 2), meter=on_level is not None)
    if cmd is None:
        return None, f"mic capture not wired for {platform.system()}"

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return None, f"couldn't start ffmpeg: {exc}"

    cue = threading.Timer(warmup, on_ready) if on_ready is not None else None
    if cue is not None:
        cue.start()

    # Drain stderr in this thread: parse loudness for the meter AND keep the tail
    # for an error message. (Draining also prevents a full-pipe deadlock.)
    tail_lines: list[str] = []
    deadline_killer = threading.Timer(seconds + warmup + 20, proc.kill)
    deadline_killer.start()
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            tail_lines.append(line)
            if len(tail_lines) > 40:
                tail_lines.pop(0)
            if on_level is not None:
                m = _M_RE.search(line)
                if m:
                    try:
                        on_level(_loudness_to_level(float(m.group(1))))
                    except Exception:
                        pass
        proc.wait()
    finally:
        deadline_killer.cancel()
        if cue is not None:
            cue.cancel()

    out = pathlib.Path(out_path)
    if proc.returncode != 0 or not out.exists():
        return None, f"recording failed (exit {proc.returncode}): {''.join(tail_lines)[-300:]}"
    return out, ""
