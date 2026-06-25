"""File tool handlers, split out as a mixin on ToolRunner.

`read_file` / `write_file` / `edit_file` / `list_dir`, plus `_resolve` — the one
chokepoint every file path passes through (it applies the sandbox policy via
self._paths, the PathResolver wired in ToolRunner.__init__). Keeping _resolve
here means the sandbox is enforced for every file handler, in one place.
"""

import pathlib

from ...config import _truncate


class FileToolsMixin:
    def _resolve(self, path: str) -> pathlib.Path:
        # Single chokepoint: the sandbox (or pass-through) policy lives in
        # PathResolver; every file handler resolves through it, never raw paths.
        return self._paths.resolve(path)

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
