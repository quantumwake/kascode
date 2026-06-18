"""Bash tool adapter: a shell command running inside a pseudo-terminal, plus
the terminal-output cleaning (ANSI strip + carriage-return overwrite emulation)
that turns raw PTY bytes into readable text for the model.
"""

import os
import pathlib
import re
import select
import signal
import subprocess
import time

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[=>()][B0]?")


def clean_terminal(text: str) -> str:
    """Strip ANSI escapes and emulate carriage-return overwrites (progress bars)."""
    text = _ANSI_RE.sub("", text)
    text = text.replace("\r\n", "\n")  # PTY line endings; lone \r = overwrite
    lines = []
    for line in text.split("\n"):
        if "\r" in line:
            line = line.split("\r")[-1]
        lines.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


# Back-compat alias (was a private name in the monolith).
_clean_terminal = clean_terminal


class BashSession:
    """A shell command running inside a pseudo-terminal.

    The PTY makes the child believe it has a real terminal, so interactive
    prompts appear in the output instead of deadlocking on a closed pipe; the
    agent can then answer them via send().
    """

    IDLE_TIMEOUT = 10.0  # no output for this long -> probably waiting for input
    WAIT_TIMEOUT = 120.0  # max time one read_until_idle() call blocks

    def __init__(self, command: str, cwd: pathlib.Path) -> None:
        import pty

        self.command = command
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            env={**os.environ, "TERM": "dumb", "npm_config_yes": "true"},
        )
        os.close(slave)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def read_until_idle(self) -> tuple[str, str]:
        """Collect output until the process exits, goes idle, or times out.

        Returns (output, status) with status in {"exited", "waiting", "timeout"}.
        """
        start = last_data = time.time()
        chunks: list[bytes] = []
        while True:
            ready, _, _ = select.select([self.master], [], [], 0.25)
            if ready:
                try:
                    data = os.read(self.master, 65536)
                except OSError:  # EIO: child side closed
                    data = b""
                if not data:
                    self.proc.wait()
                    return self._decode(chunks), "exited"
                chunks.append(data)
                last_data = time.time()
            elif not self.alive():
                return self._decode(chunks), "exited"
            elif time.time() - last_data > self.IDLE_TIMEOUT:
                return self._decode(chunks), "waiting"
            if time.time() - start > self.WAIT_TIMEOUT:
                return self._decode(chunks), "timeout"

    @staticmethod
    def _decode(chunks: list[bytes]) -> str:
        return clean_terminal(b"".join(chunks).decode(errors="replace"))

    def send(self, text: str) -> None:
        os.write(self.master, (text + "\n").encode())

    def kill(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait()
        try:
            os.close(self.master)
        except OSError:
            pass

    def close(self) -> None:
        try:
            os.close(self.master)
        except OSError:
            pass
