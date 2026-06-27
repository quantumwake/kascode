"""Speech→text via mlx-whisper (Apple Silicon).

mlx-whisper is an optional dep (`uv add mlx-whisper`). The model is a Whisper
checkpoint in MLX format — KAS_STT_MODEL overrides it; the default is a small,
fast turbo build pulled on first use. (The cached openai/whisper-* PyTorch
checkpoints aren't MLX-format, so point KAS_STT_MODEL at an mlx-community/whisper-*
repo or let the default download.) Everything here degrades gracefully: a missing
package or model returns an (error_message, True) pair rather than raising.
"""

import importlib.util
import os
import pathlib

DEFAULT_MODEL = os.environ.get("KAS_STT_MODEL", "mlx-community/whisper-large-v3-turbo")


def whisper_available() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None


def model_present(model: str | None = None) -> bool:
    """Is the whisper model already in the HF cache? (False -> first /listen will
    download it, ~1.5 GB, which looks like a hang without a notice.)"""
    import glob

    repo = (model or DEFAULT_MODEL).replace("/", "--")
    cache = os.path.expanduser(f"~/.cache/huggingface/hub/models--{repo}")
    return bool(glob.glob(f"{cache}/snapshots/*/*"))


def _missing_hint() -> str:
    return (
        "voice→text needs mlx-whisper — install it (`uv add mlx-whisper`) on Apple "
        "Silicon, then /listen again"
    )


def _load_wav_16k_mono(path: pathlib.Path):
    """Decode a PCM WAV to a float32 mono 16 kHz array — so we hand mlx-whisper
    samples directly instead of a path. That matters: given a path, mlx-whisper
    shells out to ffmpeg to decode, and spawning a subprocess from inside the
    TUI's worker thread fails with "bad value(s) in fds_to_keep" (Textual leaves
    the inherited std fds in a state fork_exec rejects). Returns None for
    non-16-bit-PCM WAVs, so the caller can fall back to the path.
    """
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if sw != 2:  # our recorder writes s16le; bail to the path for anything else
        return None
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    if sr != 16000:  # whisper wants 16 kHz — simple linear resample
        n = round(len(audio) * 16000 / sr)
        audio = np.interp(
            np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio
        ).astype(np.float32)
    return audio


def transcribe(audio_path: str | pathlib.Path, model: str | None = None) -> tuple[str, bool]:
    """Transcribe an audio file. Returns (text, is_error)."""
    if not whisper_available():
        return _missing_hint(), True
    p = pathlib.Path(audio_path)
    if not p.exists():
        return f"no audio file at {p}", True
    import mlx_whisper

    try:
        # Hand samples (not a path) to skip mlx-whisper's internal ffmpeg subprocess.
        audio = None
        try:
            audio = _load_wav_16k_mono(p)
        except Exception:
            audio = None  # unreadable/compressed WAV -> let mlx-whisper try the path
        result = mlx_whisper.transcribe(
            audio if audio is not None else str(p), path_or_hf_repo=model or DEFAULT_MODEL
        )
    except Exception as exc:  # model load / decode failures shouldn't crash the app
        return f"transcription failed: {type(exc).__name__}: {exc}", True
    return (result.get("text") or "").strip(), False
