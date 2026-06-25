"""Bash tool handlers, split out as a mixin on ToolRunner.

These are the `bash` / `bash_send_input` / `bash_wait` / `bash_kill` handlers the
model calls, plus `_session_report` (the shared PTY-read-and-summarise step). They
drive a single `self.session` (a BashSession) that ToolRunner owns — only one
shell runs at a time. `self` is the ToolRunner, so `self.io` / `self.workdir` /
`self.yolo` / `self.session` all resolve on the composed instance via the MRO.
"""

from ...config import _truncate
from .bash import BashSession


class BashToolsMixin:
    def _session_report(self) -> tuple[str, bool]:
        assert self.session is not None
        sess = self.session
        out, status = sess.read_until_idle()
        if status == "exited":
            code = sess.proc.returncode
            sess.close()
            self.session = None
            if code:
                out += f"\n[exit code {code}]"
            return _truncate(out.strip() or "(no output)"), bool(code)

        # Still running. Track consecutive *silent* waits so we can escalate the
        # guidance — and eventually stop the model from looping on bash_wait.
        if out.strip():
            sess.idle_waits = 0  # made progress this read
        elif status == "waiting":
            sess.idle_waits += 1
        waits = sess.idle_waits

        if status == "timeout":  # busy: still producing output after 120s
            note = (
                "still producing output after 120s. bash_wait to keep waiting, "
                "or bash_kill to stop it."
            )
        elif waits >= 3:
            # Break the livelock: leave it running (PTY child is its own session)
            # and free the shell so the agent can do something useful.
            cmd = sess.command
            self.session = None
            return (
                _truncate(out)
                + f"\n[no output across {waits} waits — left `{cmd}` running in the background "
                "and freed the shell. If it's a server it's ready: use it (curl/open it) or run "
                "other commands; if it's stuck, find and kill its PID. Do NOT bash_wait it again.]",
                False,
            )
        elif waits >= 2:
            note = (
                f"silent for {waits} waits — almost certainly a ready long-running process "
                "(dev server/watcher) or stuck, NOT waiting for input. Stop calling bash_wait: "
                "move on and use it, or bash_kill it."
            )
        else:
            note = (
                "no output for a while — it may be waiting for input. Answer with "
                "bash_send_input, keep waiting with bash_wait, or stop with bash_kill."
            )
        return _truncate(out) + f"\n[process still running: {note}]", False

    def tool_bash(self, command: str) -> tuple[str, bool]:
        if self.session is not None and self.session.alive():
            return (
                f"a previous command is still running (`{self.session.command}`). "
                "Interact with it via bash_send_input / bash_wait, or stop it with "
                "bash_kill before starting a new one.",
                True,
            )
        if not self.yolo:
            answer = self.io.confirm(command)
            if answer is None:
                return (
                    "cannot ask the user for confirmation (stdin is not a TTY) — "
                    "re-run the agent with --yolo to auto-approve commands",
                    True,
                )
            if answer in ("a", "always"):
                self.yolo = True
                self.io.notice("yolo enabled for this session (/yolo to turn off)")
            elif answer not in ("y", "yes"):
                return "user declined to run this command", True
        self.session = BashSession(command, self.workdir)
        return self._session_report()

    def tool_bash_send_input(self, text: str) -> tuple[str, bool]:
        if self.session is None or not self.session.alive():
            return "no command is currently running", True
        self.session.send(text)
        return self._session_report()

    def tool_bash_wait(self) -> tuple[str, bool]:
        if self.session is None or not self.session.alive():
            return "no command is currently running", True
        return self._session_report()

    def tool_bash_kill(self) -> tuple[str, bool]:
        if self.session is None:
            return "no command is currently running", True
        self.session.kill()
        self.session = None
        return "process terminated", False
