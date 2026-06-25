"""Architecture guard (v3 Phase 5): the hexagonal core must never import a
concrete driven adapter. Statically scans every module under agent/core/ and
server/core/ for an import of an `adapters` OR `backends` package (the
implementation layers) and fails if the dependency direction is ever violated —
core may depend only on ports. Locks, in CI, the property that holds by
discipline. No model/server needed.

Run:  uv run python tests/test_architecture.py
"""

import ast
import pathlib
import sys

sys.path.insert(0, ".")

ROOT = pathlib.Path(__file__).parent.parent
CORE_DIRS = [ROOT / "agent" / "core", ROOT / "server" / "core"]
# Implementation packages the core must not reach into (it depends on ports only).
FORBIDDEN = {"adapters", "backends"}


def _forbidden_imports(path: pathlib.Path) -> list[str]:
    """Module names this file imports that live under a forbidden impl package."""
    tree = ast.parse(path.read_text())
    bad: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and FORBIDDEN & set(node.module.split("."))
        ):
            bad.append(node.module)
        elif isinstance(node, ast.Import):
            bad += [a.name for a in node.names if FORBIDDEN & set(a.name.split("."))]
    return bad


violations: list[str] = []
scanned = 0
for d in CORE_DIRS:
    for path in d.rglob("*.py"):
        scanned += 1
        for mod in _forbidden_imports(path):
            violations.append(f"{path.relative_to(ROOT)} imports {mod!r}")

assert not violations, "core must not import adapters/backends:\n  " + "\n  ".join(violations)
print(f"core-isolation: OK ({scanned} core modules, 0 adapter/backend imports)")
print("all architecture tests passed")
