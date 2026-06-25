"""Smoke test for the version string (scripts.version): it's well-formed and
always starts with the packaged base version. In this checkout it also carries
git build metadata. No model/server needed.

Run:  uv run python tests/test_version.py
"""

import sys

sys.path.insert(0, ".")

from scripts.version import _packaged, kas_version

base = _packaged()
v = kas_version()

assert isinstance(v, str) and v, repr(v)
assert v.startswith(base), (v, base)  # the packaged base is always the prefix
# Running from a git checkout (this repo): either exactly on a tag (== base) or
# carrying build metadata (build./+build./branch-prefix).
assert v == base or "build." in v, v
# the build-number segment, when present, is numeric
if "build." in v:
    seg = v.split("build.", 1)[1].split(".")[0]
    assert seg.isdigit(), v

print(f"version: {v}")
print("all version tests passed")
