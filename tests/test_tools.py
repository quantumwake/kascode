"""Characterization tests for the agent's ToolRunner: file tools, dispatch,
and error surfacing. Locks behaviour before the hexagonal refactor extracts
these into agent/adapters/tools/*. No model or server needed.

Run:  uv run python tests/test_tools.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

from agent.main import ToolRunner


class FakeIO:
    def __init__(self, answer="y"):
        self.answer = answer
        self.notices = []

    def confirm(self, command):
        return self.answer

    def notice(self, text):
        self.notices.append(text)


def runner(tmp, **kw):
    return ToolRunner(pathlib.Path(tmp), yolo=True, io=FakeIO(), **kw)


with tempfile.TemporaryDirectory() as tmp:
    r = runner(tmp)

    # write_file -> read_file round-trip.
    out, err = r.tool_write_file("a.txt", "hello\nworld\n")
    assert not err and "wrote" in out, (out, err)
    out, err = r.tool_read_file("a.txt")
    assert not err and out == "hello\nworld\n", repr(out)

    # append mode.
    out, err = r.tool_write_file("a.txt", "again\n", append=True)
    assert not err and "appended" in out, out
    assert r.tool_read_file("a.txt")[0] == "hello\nworld\nagain\n"

    # ranged read is line-number prefixed.
    out, err = r.tool_read_file("a.txt", start_line=2, end_line=2)
    assert not err and "world" in out and "[lines 2-2 of 3]" in out, repr(out)

    # edit_file: unique match required.
    out, err = r.tool_edit_file("a.txt", "world", "WORLD")
    assert not err and "edited" in out, (out, err)
    assert "WORLD" in r.tool_read_file("a.txt")[0]

    out, err = r.tool_edit_file("a.txt", "missing", "x")
    assert err and "not found" in out, (out, err)

    r.tool_write_file("dup.txt", "x\nx\n")
    out, err = r.tool_edit_file("dup.txt", "x", "y")
    assert err and "appears 2 times" in out, (out, err)

    # list_dir.
    out, err = r.tool_list_dir(".")
    assert not err and "a.txt" in out and "dup.txt" in out, out
    print("file tools: OK")


# ---------------------------------------------------------------------------
# run() dispatch + error surfacing
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    r = runner(tmp)

    # unknown tool name.
    out, err = r.run("does_not_exist", {})
    assert err and "unknown tool" in out, (out, err)

    # non-mutating dispatch goes through and does not flip `mutated`.
    out, err = r.run("list_dir", {"path": "."})
    assert not err and not r.mutated, (out, err, r.mutated)

    # exceptions inside a handler are surfaced as a tool error, not raised.
    out, err = r.run("read_file", {"path": "nope.txt"})
    assert err and ("FileNotFoundError" in out or "No such file" in out), (out, err)
    print("dispatch + errors: OK")


# ---------------------------------------------------------------------------
# --sandbox: file tools jailed to the workdir
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    # Default (sandbox off): absolute paths outside workdir still work.
    r = runner(tmp)
    out, err = r.tool_write_file("/tmp/kas_sandbox_off_probe.txt", "x")
    assert not err, (out, err)  # legacy behaviour preserved
    pathlib.Path("/tmp/kas_sandbox_off_probe.txt").unlink(missing_ok=True)

    # Sandbox on: in-workdir paths allowed, escapes refused via run() error.
    rs = runner(tmp, sandbox=True)
    out, err = rs.tool_write_file("inside.txt", "ok")
    assert not err, (out, err)

    out, err = rs.run("write_file", {"path": "/etc/kas_should_not_write", "content": "x"})
    assert err and "sandbox" in out.lower(), (out, err)

    out, err = rs.run("read_file", {"path": "../../../../etc/hosts"})
    assert err and "sandbox" in out.lower(), (out, err)

    out, err = rs.run("list_dir", {"path": "/"})
    assert err and "sandbox" in out.lower(), (out, err)
    print("sandbox jail: OK")

print("all tool tests passed")
