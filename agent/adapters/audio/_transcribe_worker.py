"""mlx-whisper in a CLEAN, isolated subprocess — and, in --serve mode, a
LONG-LIVED one that loads the model ONCE and transcribes many clips, so /listen
isn't paying the model-load cost every time.

Isolation matters: spawning whisper from inside the TUI's worker thread inherits
Textual's std fds and dies with "bad value(s) in fds_to_keep" when whisper (or a
dep) forks. A fresh process sidesteps that; a persistent one also stays warm.

Streams newline-delimited JSON on stdout:
  {"event":"ready"}                       (serve mode: model loaded, send paths)
  {"event":"loading","model":...}
  {"event":"transcribing","audio_secs":5.0}
  {"event":"done","text":"..."}  |  {"event":"error","msg":<traceback>}

  python -m agent.adapters.audio._transcribe_worker <wav> <model>     # one-shot
  python -m agent.adapters.audio._transcribe_worker --serve <model>   # server
      (then write one wav path per line on stdin; a {"done"|"error"} per line)
"""

import json
import pathlib
import sys


def _emit(**d) -> None:
    sys.stdout.write(json.dumps(d) + "\n")
    sys.stdout.flush()


def _transcribe_one(wav: str, model: str) -> None:
    from .stt import _load_wav_16k_mono

    audio = _load_wav_16k_mono(pathlib.Path(wav))
    if audio is None:
        _emit(event="error", msg="unsupported audio format (need a PCM WAV)")
        return
    if len(audio) == 0:
        _emit(event="error", msg="no audio captured (check mic permission)")
        return
    import mlx_whisper

    _emit(event="transcribing", audio_secs=round(len(audio) / 16000, 1))
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=model)
    _emit(event="done", text=(result.get("text") or "").strip())


def _serve(model: str) -> int:
    """Load the model once (warm it on a short silent buffer), then transcribe a
    wav path per stdin line until EOF. mlx-whisper caches the loaded model, so
    every subsequent clip skips the load."""
    try:
        import mlx_whisper
        import numpy as np

        _emit(event="loading", model=model)
        mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=model)
        _emit(event="ready")
    except Exception:
        import traceback

        _emit(event="error", msg=traceback.format_exc())
        return 1
    for line in sys.stdin:
        wav = line.strip()
        if not wav:
            continue
        try:
            _transcribe_one(wav, model)
        except Exception:
            import traceback

            _emit(event="error", msg=traceback.format_exc())
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--serve":
        if len(args) < 2:
            _emit(event="error", msg="usage: --serve <model>")
            return 2
        return _serve(args[1])
    if len(args) < 2:
        _emit(event="error", msg="usage: _transcribe_worker <wav> <model>")
        return 2
    try:
        _emit(event="loading", model=args[1])
        _transcribe_one(args[0], args[1])
        return 0
    except Exception:
        import traceback

        _emit(event="error", msg=traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
