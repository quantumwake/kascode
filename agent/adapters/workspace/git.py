"""Workspace checkpointing: per-turn git commits so the user can inspect or
revert what the agent changed. Decides once whether a given workdir is eligible
(a fresh dir we init, a dir gitignored by an enclosing repo, or one we already
manage) — a user's own repo is never auto-committed to unless --checkpoint.
"""

import pathlib
import subprocess

WORKSPACE_GITIGNORE = ".agent/\nnode_modules/\n.venv/\n__pycache__/\n.DS_Store\n"


class GitWorkspace:
    def __init__(self, workdir: pathlib.Path, io, force_checkpoint: bool = False) -> None:
        self.workdir = workdir
        self.io = io
        self.force_checkpoint = force_checkpoint  # commit even into a pre-existing repo
        self._repo: bool | None = None  # lazily decided

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.workdir, capture_output=True, text=True, timeout=60
        )

    def ready(self) -> bool:
        """Decide once whether this workdir gets per-turn commits.

        Yes when: we already initialized it (marker), the dir is not in any
        repo (init one), or it sits inside a repo but is gitignored by it —
        the 'outputs as separate nested repos' case. A user's existing repo is
        never auto-committed to unless --checkpoint was passed.
        """
        if self._repo is not None:
            return self._repo
        marker = self.workdir / ".agent" / "workspace-repo"
        if marker.exists():
            self._repo = True
            return True
        inside = self._git("rev-parse", "--is-inside-work-tree").returncode == 0
        nested_ok = False
        if inside:
            has_own_git = (self.workdir / ".git").exists()
            ignored = self._git("check-ignore", "-q", str(self.workdir)).returncode == 0
            if has_own_git:
                self._repo = True  # already its own repo
                return True
            if not ignored and not self.force_checkpoint:
                self._repo = False  # someone else's repo — hands off
                return False
            nested_ok = ignored
        if not inside or nested_ok:
            self._git("init", "-q", "-b", "main")
            gi = self.workdir / ".gitignore"
            if not gi.exists():
                gi.write_text(WORKSPACE_GITIGNORE)
            self._git("add", "-A")
            self._git("commit", "-q", "-m", "baseline (before agent changes)")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("initialized by local-agent\n")
            self.io.notice(f"[workspace repo initialized: {self.workdir}]")
        self._repo = True
        return True

    def checkpoint(self, mutated: bool, label: str) -> str | None:
        """Commit this turn's changes; returns the short sha or None."""
        if not mutated:
            return None
        try:
            if not self.ready():
                return None
            self._git("add", "-A")
            if self._git("diff", "--cached", "--quiet").returncode == 0:
                return None  # nothing actually changed
            self._git("commit", "-q", "-m", f"agent: {label}")
            return self._git("rev-parse", "--short", "HEAD").stdout.strip() or None
        except Exception:
            return None  # checkpointing must never break the loop
