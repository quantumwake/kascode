"""Plain-terminal UI adapter (REPL / one-shot mode) and the quiet-stream
heartbeat. Implements the AgentIO port for a real terminal.
"""

import json
import sys
import threading
import time

import httpx


class Heartbeat:
    """Shows a live status line whenever the response stream goes quiet.

    Long tool calls are buffered server-side until they close, so the client
    can see nothing for minutes. This thread polls GET /v1/stats and renders
    e.g. `⏳ generating 312 tok @ 10.8 tok/s · 29s` until output resumes.
    """

    QUIET_AFTER = 2.0  # seconds of stream silence before the line appears

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.last_activity = time.time()
        self.showing = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _status_line(self) -> str:
        try:
            s = httpx.get(self.base_url + "/v1/stats", timeout=2).json()
        except Exception:
            return "waiting for server..."
        if not s.get("active"):
            return "waiting..."
        if s.get("phase") == "prefill":
            return (
                f"⏳ prefill {s['processed']}/{s['total']} tok "
                f"(cache hit {s['cached']}) · {s['elapsed']:.0f}s"
            )
        return f"⏳ generating {s['generated']} tok @ {s['tps']} tok/s · {s['elapsed']:.0f}s"

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            if time.time() - self.last_activity < self.QUIET_AFTER:
                continue
            sys.stdout.write(f"\r\033[2m{self._status_line()}\033[0m\033[K")
            sys.stdout.flush()
            self.showing = True

    def tick(self) -> None:
        """Call before printing real output: clears the status line."""
        self.last_activity = time.time()
        if self.showing:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self.showing = False

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        if self.showing:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self.showing = False


class ConsoleIO:
    """Plain-terminal presentation of an agent turn (REPL / one-shot mode)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.hb: Heartbeat | None = None
        self._t0 = 0.0
        self._ttft: float | None = None
        self.last_decode_tps: float = 0.0  # decode rate of the most recent turn

    # -- streaming -----------------------------------------------------------
    def stream_started(self) -> None:
        self._t0, self._ttft = time.time(), None
        self.hb = Heartbeat(self.base_url)

    def delta(self, kind: str, text: str) -> None:
        if self._ttft is None:
            self._ttft = time.time() - self._t0
        if self.hb:
            self.hb.tick()
        if kind == "thinking":
            print(f"\033[2m{text}\033[0m", end="", flush=True)
        else:
            print(text, end="", flush=True)

    def stream_finished(self, usage) -> None:
        if self.hb:
            self.hb.stop()
            self.hb = None
        if usage is not None:
            decode_t = max(0.05, (time.time() - self._t0) - (self._ttft or 0))
            self.last_decode_tps = usage.output_tokens / decode_t
            print(
                f"\n\033[2m[{usage.input_tokens} in / {usage.output_tokens} out · "
                f"ttft {self._ttft or 0:.1f}s · {self.last_decode_tps:.1f} tok/s · "
                f"total {time.time() - self._t0:.1f}s]\033[0m"
            )

    # -- tool activity ---------------------------------------------------------
    def tool_call(self, name: str, args: dict) -> None:
        print(f"\n→ {name}({json.dumps(args, ensure_ascii=False)[:200]})")

    def tool_result(self, output: str, is_error: bool) -> None:
        preview = output if len(output) < 300 else output[:300] + "..."
        print(f"  {'✗' if is_error else '✓'} {preview}")

    def notice(self, text: str) -> None:
        print(f"\033[33m{text}\033[0m")

    # -- interaction -----------------------------------------------------------
    def confirm(self, command: str) -> str | None:
        """Ask y/N/a. Returns the answer, or None when no TTY is available."""
        import termios

        if not sys.stdin.isatty():
            return None
        # Keystrokes typed while the model was generating sit in the stdin
        # buffer and would be consumed as an instant (empty -> decline)
        # answer. Flush them so the question is genuinely asked.
        try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
        return input(f"\n  \033[1mrun `{command}`? [y/N/a=always]\033[0m ").strip().lower()

    def drain_steers(self) -> list[str]:
        return []  # console mode has no mid-run input channel

    def should_abort(self) -> bool:
        return False  # console mode has no mid-run interrupt channel

    def should_pause(self) -> bool:
        return False  # console mode has no pause channel

    def clear_abort(self) -> None:
        pass
