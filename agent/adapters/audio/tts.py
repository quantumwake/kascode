"""Text→speech for spoken assistant replies.

Tiered, so it works out of the box and scales up:
  1. a native OS voice — macOS `say`, Linux `espeak-ng`/`espeak`/`spd-say` — no
     model download, always there;
  2. a neural backend (mlx-audio / Kokoro) when KAS_TTS=mlx and the package +
     a model are present — higher quality, opt-in.

Speech runs in a detached subprocess so it never blocks the UI, and starting a
new utterance interrupts the previous one (so a fresh turn cuts off stale
speech). Everything degrades to a clear (message, True) rather than raising.
"""

import os
import platform
import shutil
import subprocess

_proc: subprocess.Popen | None = None


def _native_cmd(text: str) -> list[str] | None:
    """A native TTS command for this OS, or None if none is on PATH."""
    if platform.system() == "Darwin" and shutil.which("say"):
        voice = os.environ.get("KAS_TTS_VOICE")
        return ["say", *(["-v", voice] if voice else []), text]
    for bin_ in ("espeak-ng", "espeak", "spd-say"):
        if shutil.which(bin_):
            return [bin_, text]
    return None


def available() -> bool:
    return _native_cmd("x") is not None or _mlx_available()


def _mlx_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("mlx_audio") is not None


def stop() -> None:
    """Interrupt any in-flight speech."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
        except Exception:
            pass
    _proc = None


def wait() -> None:
    """Block until the current utterance finishes (or is stopped). For driving a
    'speaking' indicator off-thread — never call it on the UI thread."""
    proc = _proc
    if proc is not None:
        try:
            proc.wait()
        except Exception:
            pass


def speak(text: str) -> tuple[str, bool]:
    """Speak `text` in the background (non-blocking). Returns ("", False) on
    success or (message, True) when no engine is available."""
    stop()
    text = (text or "").strip()
    if not text:
        return "", False
    cmd = _mlx_cmd(text) if os.environ.get("KAS_TTS") == "mlx" else None
    cmd = cmd or _native_cmd(text)
    if cmd is None:
        return (
            "no TTS engine — macOS has `say`; on Linux install espeak-ng; or set "
            "KAS_TTS=mlx with mlx-audio",
            True,
        )
    global _proc
    try:
        _proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"could not start TTS: {exc}", True
    return "", False


def _mlx_cmd(text: str) -> list[str] | None:
    """mlx-audio CLI invocation when configured + installed (else None -> native)."""
    if not _mlx_available():
        return None
    model = os.environ.get("KAS_TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
    return ["python", "-m", "mlx_audio.tts.generate", "--model", model, "--text", text, "--play"]
