"""ToolRunner — the ToolExecutor adapter: dispatches a tool call to its handler
and coordinates per-turn workspace checkpointing. The heavy collaborators live
in sibling modules (BashSession, PathResolver, Recaller, web fns, GitWorkspace);
this class wires them and keeps the thin tool_* handlers the model calls.
"""

import pathlib
from collections import deque

from ...config import _truncate
from ..workspace.git import GitWorkspace
from .bash import BashSession
from .files import PathResolver
from .recall import Recaller
from .web import web_fetch, web_search


class ToolRunner:
    MUTATING_TOOLS = ("write_file", "edit_file", "bash", "bash_send_input")

    def __init__(
        self,
        workdir: pathlib.Path,
        yolo: bool,
        io=None,
        checkpoint: bool = False,
        net: bool = False,
        rag: bool = False,
        context_limit: int | None = None,
        sandbox: bool = False,
    ) -> None:
        self.workdir = workdir
        self.yolo = yolo
        if io is None:
            from ...config import BASE_URL
            from ..ui.console import ConsoleIO

            io = ConsoleIO(BASE_URL)
        self.io = io
        self.net = net  # web_search / web_fetch available only when True
        self.rag = rag  # recall tool available only when True
        self.context_limit = context_limit  # model's native context window (overflow safety)
        self.tps_window: deque = deque(maxlen=4)  # recent decode tok/s, for the trigger
        self.session: BashSession | None = None
        self.mutated = False  # any tool may have changed files this turn
        self._paths = PathResolver(workdir, sandbox=sandbox)
        self._recaller = Recaller(workdir)
        self.git = GitWorkspace(workdir, io, force_checkpoint=checkpoint)
        # context size right after the last compaction; auto-compaction
        # triggers on GROWTH beyond this, not on an absolute threshold —
        # otherwise post-compaction re-reads immediately re-trigger it
        self.compact_floor = 0
        self.compact_cooldown = 0  # turns remaining before compaction may fire again

    # -- workspace checkpointing ----------------------------------------------

    def checkpoint(self, label: str) -> str | None:
        """Commit this turn's changes; returns the short sha or None."""
        mutated, self.mutated = self.mutated, False
        return self.git.checkpoint(mutated, label)

    # -- dispatch -------------------------------------------------------------

    def _resolve(self, path: str) -> pathlib.Path:
        return self._paths.resolve(path)

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (output, is_error)."""
        try:
            handler = getattr(self, f"tool_{name}", None)
            if handler is None:
                return f"unknown tool: {name}", True
            if name in self.MUTATING_TOOLS:
                # Ensure the workspace repo (and its pre-agent baseline commit)
                # exists BEFORE the first change lands.
                try:
                    self.git.ready()
                except Exception:
                    pass
            output, is_error = handler(**args)
            if not is_error and name in self.MUTATING_TOOLS:
                self.mutated = True  # may have changed the workspace
            return output, is_error
        except Exception as exc:  # surface errors to the model, don't crash
            return f"{type(exc).__name__}: {exc}", True

    # -- bash -----------------------------------------------------------------

    def _session_report(self) -> tuple[str, bool]:
        assert self.session is not None
        out, status = self.session.read_until_idle()
        if status == "exited":
            code = self.session.proc.returncode
            self.session.close()
            self.session = None
            if code:
                out += f"\n[exit code {code}]"
            return _truncate(out.strip() or "(no output)"), bool(code)
        hint = (
            "no output for 10s — it is probably waiting for input"
            if status == "waiting"
            else "still producing output after 120s"
        )
        return (
            _truncate(out)
            + f"\n[process still running: {hint}. Use bash_send_input to answer a "
            "prompt, bash_wait to keep waiting, or bash_kill to stop it.]",
            False,
        )

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

    # -- files ----------------------------------------------------------------

    def tool_read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> tuple[str, bool]:
        text = self._resolve(path).read_text()
        if start_line is None and end_line is None:
            return _truncate(text), False
        lines = text.splitlines()
        lo = max(1, start_line or 1)
        hi = min(len(lines), end_line or len(lines))
        if lo > len(lines):
            return f"start_line {lo} is past end of file ({len(lines)} lines)", True
        body = "\n".join(f"{i:>5}: {lines[i - 1]}" for i in range(lo, hi + 1))
        return _truncate(f"[lines {lo}-{hi} of {len(lines)}]\n{body}"), False

    def tool_write_file(self, path: str, content: str, append: bool = False) -> tuple[str, bool]:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a" if append else "w") as f:
            f.write(content)
        verb = "appended" if append else "wrote"
        return f"{verb} {len(content)} chars to {p}", False

    def tool_edit_file(self, path: str, old_string: str, new_string: str) -> tuple[str, bool]:
        p = self._resolve(path)
        text = p.read_text()
        count = text.count(old_string)
        if count == 0:
            return "old_string not found in file", True
        if count > 1:
            return f"old_string appears {count} times; it must be unique", True
        p.write_text(text.replace(old_string, new_string, 1))
        return f"edited {p}", False

    def tool_list_dir(self, path: str = ".") -> tuple[str, bool]:
        entries = sorted(self._resolve(path).iterdir())
        return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries) or "(empty)", False

    # -- opt-in tools ---------------------------------------------------------

    def tool_recall(self, query: str, k: int = 8) -> tuple[str, bool]:
        return self._recaller.search(query, k)

    def tool_web_search(self, query: str, max_results: int = 5) -> tuple[str, bool]:
        return web_search(query, max_results)

    def tool_web_fetch(self, url: str) -> tuple[str, bool]:
        return web_fetch(url)
