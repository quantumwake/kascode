"""Smoke-test the voice→text pipeline END TO END, outside the TUI, with full
tracebacks — so a failure is visible and fast to iterate on.

  make smoke-test-voice                # record 3s from the mic, then transcribe
  make smoke-test-voice SECS=5         # record 5s
  make smoke-test-voice SAY="hello"    # skip the mic — synthesize speech via `say`

It runs transcription on a WORKER THREAD (like /listen does), prints the env /
deps / model state up front, and never swallows errors — whatever breaks, you
see the real exception here instead of a one-line failure in the TUI.
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import traceback

sys.path.insert(0, ".")

from agent.adapters.audio import record as rec  # noqa: E402
from agent.adapters.audio import stt  # noqa: E402


def main() -> int:
    secs = int(os.environ.get("SECS") or "3")
    say = os.environ.get("SAY") or ""

    print("── voice smoke test ──────────────────────────────")
    print(f"  python : {sys.executable}")
    print(f"  mlx-whisper installed : {stt.whisper_available()}")
    print(f"  model  : {stt.DEFAULT_MODEL}")
    print(f"  model cached : {stt.model_present()} (first run downloads ~1.5 GB)")
    if not stt.whisper_available():
        print("\n  ✗ mlx-whisper isn't installed in THIS python env.")
        print("    install:  uv pip install --python", sys.executable, "mlx-whisper")
        return 1

    wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
    if say:
        print(f"\n  [say] synthesizing {say!r} → {wav.name}")
        subprocess.run(
            ["say", "--data-format=LEI16@16000", "-o", str(wav), say],
            check=True,
            stdin=subprocess.DEVNULL,
        )
    else:
        print(f"\n  [mic] recording {secs}s — SPEAK NOW…")
        path, err = rec.record(wav, secs)
        if err:
            print(f"  ✗ recording failed: {err}")
            return 1
        size = wav.stat().st_size if wav.exists() else 0
        print(f"  [mic] captured {size} bytes")
        if size < 1000:
            print("  ⚠ tiny capture — likely no mic permission (System Settings → Microphone)")

    # Decode preview (proves we hand whisper SAMPLES, never a path → no ffmpeg fork)
    try:
        arr = stt._load_wav_16k_mono(wav)
        print(f"  [decode] {None if arr is None else (str(arr.dtype), len(arr))} samples")
    except Exception:
        print("  [decode] failed:\n" + traceback.format_exc())

    # Transcribe on a worker thread, exactly like /listen, printing progress.
    out: dict = {}

    def progress(ev: dict) -> None:
        print(f"  [progress] {ev}")

    def work() -> None:
        try:
            out["text"], out["err"] = stt.transcribe(wav, on_progress=progress)
        except Exception:
            out["trace"] = traceback.format_exc()

    t = threading.Thread(target=work)
    t.start()
    t.join()

    print()
    if "trace" in out:
        print("  ✗ transcribe CRASHED:\n" + out["trace"])
        return 1
    if out.get("err"):
        print(f"  ✗ transcribe failed: {out['text']}")
        return 1
    print(f"  ✓ transcript: {out['text']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
