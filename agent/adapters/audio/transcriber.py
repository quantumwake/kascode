"""A warm, isolated transcription worker: one long-lived subprocess that loads
the whisper model once and transcribes many clips. Solves both problems at once
— the subprocess is fd-isolated (no 'fds_to_keep' fork crash from the TUI), and
keeping it alive means /listen pays the model-load cost ONLY on first use
(preload), not every time.

Thread-safe: one transcription at a time behind a lock (the TUI does one /listen
at a time). A dead worker is transparently respawned on the next call.
"""

import json
import os
import subprocess
import sys
import threading


class Transcriber:
    def __init__(self, model: str) -> None:
        self.model = model
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # --- lifecycle ----------------------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> tuple[bool, str]:
        """Start the serve-mode worker and block until it's loaded (or errors).
        Returns (ok, message)."""
        cmd = [
            sys.executable,
            "-m",
            "agent.adapters.audio._transcribe_worker",
            "--serve",
            self.model,
        ]
        # stderr=DEVNULL: whisper/hf write progress there; piping it unread would
        # deadlock the worker. Status comes back as JSON on stdout.
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        load_timeout = float(os.environ.get("KAS_STT_LOAD_TIMEOUT", "600"))
        killer = threading.Timer(load_timeout, self._kill)
        killer.start()
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:  # read until ready/error
                ev = _parse(line)
                if ev.get("event") == "ready":
                    return True, "ready"
                if ev.get("event") == "error":
                    return False, _last_line(ev.get("msg", "load failed"))
            return False, "worker exited during load"
        finally:
            killer.cancel()

    def _kill(self) -> None:
        try:
            if self._proc:
                self._proc.kill()
        except Exception:
            pass

    def preload(self) -> tuple[bool, str]:
        """Start the worker + load the model now (call when voice is activated)."""
        with self._lock:
            if self._alive():
                return True, "already loaded"
            return self._spawn()

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            self._kill()
            self._proc = None

    # --- transcription ------------------------------------------------------

    def transcribe(self, wav_path: str, on_progress=None) -> tuple[str, bool]:
        """Transcribe `wav_path`. Returns (text, is_error). Respawns a dead
        worker. A watchdog kills a hung worker so this never blocks forever."""
        with self._lock:
            if not self._alive():
                ok, msg = self._spawn()
                if not ok:
                    return f"transcription worker failed to start: {msg}", True
            assert self._proc is not None and self._proc.stdin and self._proc.stdout

            timeout = float(os.environ.get("KAS_STT_TIMEOUT", "180"))
            timed_out = threading.Event()

            def _trip() -> None:
                timed_out.set()
                self._kill()  # unblocks the readline below (EOF)

            watchdog = threading.Timer(timeout, _trip)
            watchdog.start()
            try:
                self._proc.stdin.write(wav_path + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                watchdog.cancel()
                self._proc = None
                return "transcription worker died — retry /listen", True

            text: str | None = None
            err: str | None = None
            try:
                for line in self._proc.stdout:
                    ev = _parse(line)
                    kind = ev.get("event")
                    if kind == "done":
                        text = (ev.get("text") or "").strip()
                        break
                    if kind == "error":
                        err = _last_line(ev.get("msg", "unknown error"))
                        break
                    if on_progress is not None:
                        try:
                            on_progress(ev)
                        except Exception:
                            pass
            finally:
                watchdog.cancel()

            if timed_out.is_set():
                self._proc = None
                return f"transcription timed out after {timeout:.0f}s (KAS_STT_TIMEOUT)", True
            if err is not None:
                return f"transcription failed: {err}", True
            if text is None:
                self._proc = None  # worker closed unexpectedly
                return "transcription worker closed unexpectedly", True
            return text, False


def _parse(line: str) -> dict:
    line = line.strip()
    if not line:
        return {}
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {}


def _last_line(msg: str) -> str:
    msg = (msg or "").strip()
    return msg.splitlines()[-1] if msg else "unknown error"
