"""Text→speech for spoken assistant replies — with a voice-FX layer.

Pipeline:  synth (Kokoro / native) → optional ffmpeg FX → play.

  - engine: KAS_TTS = mlx | native | auto (default auto = Kokoro when mlx-audio
    is installed, else the native OS voice — macOS `say`, Linux `espeak-ng`).
  - character: KAS_TTS_FX = warrior (default) | none, or KAS_TTS_FILTER for a raw
    ffmpeg -af chain. The default "warrior" preset pitches the voice down and
    adds hall reverb + a chorus shimmer + compression — deep, powerful, alien.
    Needs ffmpeg (already required for voice capture); without it, the dry voice
    plays.
  - voice: KAS_KOKORO_VOICE (Kokoro id, default am_onyx = deep male) ·
    KAS_TTS_VOICE (a macOS `say` voice, default Daniel) · KAS_TTS_PITCH /
    KAS_TTS_RATE tune the native pitch/rate before FX.

Speech runs in a detached process group so it never blocks the UI; a new
utterance interrupts the previous one. Everything degrades to (message, True).
"""

import os
import pathlib
import platform
import shlex
import shutil
import subprocess
import tempfile

_proc: subprocess.Popen | None = None

_KOKORO_DEFAULT = "am_onyx"  # deep male; bm_george (UK) / af_heart (warm) etc.
_NATIVE_DEFAULT = "Daniel"  # en_GB — the deepest real voice usually present

# The voice-character FX chains (ffmpeg -af). Sample-rate-independent: normalise
# to 44.1k, drop the pitch ~18% (asetrate), restore tempo, then space + shimmer +
# power. "warrior" = deep/alien/powerful.
_FX_PRESETS = {
    "warrior": (
        "aresample=44100,asetrate=36162,aresample=44100,atempo=1.18,"
        "aecho=0.8:0.85:55:0.35,chorus=0.6:0.9:50:0.4:0.25:2,"
        "acompressor=threshold=-18dB:ratio=4,alimiter"
    ),
    "none": "",
}


def _fx_filter() -> str:
    """The ffmpeg -af chain for the configured character, or "" for none."""
    raw = os.environ.get("KAS_TTS_FILTER")
    if raw is not None:
        return raw
    preset = os.environ.get("KAS_TTS_FX", "warrior").lower()
    return _FX_PRESETS.get(preset, _FX_PRESETS["warrior"])


def _mlx_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("mlx_audio") is not None


def _native_synth(text: str, out: str) -> list[str] | None:
    """Argv that synthesises `text` to the audio file `out` with a native engine,
    or None if none is available."""
    if platform.system() == "Darwin" and shutil.which("say"):
        voice = os.environ.get("KAS_TTS_VOICE", _NATIVE_DEFAULT)
        pitch = os.environ.get("KAS_TTS_PITCH", "18")  # say [[pbas]] base pitch
        rate = os.environ.get("KAS_TTS_RATE", "155")  # words per minute
        body = f"[[pbas {pitch}]] [[rate {rate}]] {text}"
        return ["say", "-v", voice, "-o", out, body]
    for bin_ in ("espeak-ng", "espeak"):
        if shutil.which(bin_):
            rate = os.environ.get("KAS_TTS_RATE", "150")
            return [bin_, "-p", "20", "-s", rate, "-w", out, text]
    return None


def _kokoro_synth(text: str, out: str) -> str | None:
    """A shell snippet that synthesises `text` to `out` via mlx-audio (Kokoro),
    or None if not installed. (Kokoro writes <prefix>*.wav; we take the newest
    and move it to `out` so the rest of the pipeline is engine-agnostic.)"""
    if not _mlx_available():
        return None
    model = os.environ.get("KAS_TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
    voice = os.environ.get("KAS_KOKORO_VOICE", _KOKORO_DEFAULT)
    prefix = out + ".koko"
    gen = (
        f"python -m mlx_audio.tts.generate --model {shlex.quote(model)} "
        f"--voice {shlex.quote(voice)} --text {shlex.quote(text)} "
        f"--file_prefix {shlex.quote(prefix)}"
    )
    # move the produced wav to the canonical out path
    return f'{gen} && mv "$(ls -t {shlex.quote(prefix)}*.wav | head -1)" {shlex.quote(out)}'


def _play_argv(path: str) -> list[str] | None:
    if platform.system() == "Darwin" and shutil.which("afplay"):
        return ["afplay", path]
    for bin_, args in (
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
        ("aplay", []),
        ("paplay", []),
    ):
        if shutil.which(bin_):
            return [bin_, *args, path]
    return None


def _pipeline(text: str) -> list[str] | None:
    """Build the full detached `sh -c` command: synth → (ffmpeg FX) → play, or
    None if no engine/player is available."""
    engine = os.environ.get("KAS_TTS", "auto").lower()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="kas-tts-"))
    raw, played = str(tmp / "raw.wav"), str(tmp / "out.wav")

    synth: str | None = None
    if engine != "native":  # auto / mlx: prefer Kokoro when present
        synth = _kokoro_synth(text, raw)
    if synth is None:  # native (forced, or Kokoro absent)
        argv = _native_synth(text, raw)
        synth = shlex.join(argv) if argv else None
    if synth is None:
        return None

    fx = _fx_filter()
    use_fx = bool(fx) and shutil.which("ffmpeg") is not None
    target = played if use_fx else raw
    play = _play_argv(target)
    if play is None:
        return None

    steps = [synth]
    if use_fx:
        steps.append(
            f"ffmpeg -y -loglevel quiet -i {shlex.quote(raw)} -af {shlex.quote(fx)} "
            f"{shlex.quote(played)}"
        )
    steps.append(shlex.join(play))
    steps.append(f"rm -rf {shlex.quote(str(tmp))}")  # best-effort cleanup
    return ["sh", "-c", " && ".join(steps[:-1]) + "; " + steps[-1]]


def available() -> bool:
    return _mlx_available() or _native_synth("x", "/tmp/x") is not None


def stop() -> None:
    """Interrupt any in-flight speech (the whole process group: synth/ffmpeg/play)."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        try:
            os.killpg(os.getpgid(_proc.pid), 15)
        except Exception:
            try:
                _proc.terminate()
            except Exception:
                pass
    _proc = None


def wait() -> None:
    """Block until the current utterance finishes (or is stopped). Off-thread only."""
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
    cmd = _pipeline(text)
    if cmd is None:
        return (
            "no TTS engine — macOS has `say`; on Linux install espeak-ng; or add "
            "mlx-audio for neural Kokoro voices (kas doctor --install)",
            True,
        )
    global _proc
    try:
        _proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
    except OSError as exc:
        return f"could not start TTS: {exc}", True
    return "", False
