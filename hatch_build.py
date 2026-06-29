"""Hatchling build hook: stamp the git commit into the wheel.

scripts/version.py derives build info from git, but an INSTALLED package has no
checkout to read — so the version collapses to the bare "0.1.0" and you can't
tell which build you're running. At build time the source DOES have a .git (uv
clones it for `git+https` installs, and a dev checkout obviously has one), so we
capture the short commit + build number here and write them into the package as
scripts/_build_info.py. version.py reads that when there's no usable checkout.

Resilient by design: if git isn't available at build time (e.g. building from an
sdist with no .git), it writes nothing and version.py falls back to "0.1.0".
"""

import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class BuildCommitHook(BuildHookInterface):
    PLUGIN_NAME = "build-commit"

    def initialize(self, version, build_data):
        root = Path(self.root)

        def git(*args: str) -> str:
            try:
                r = subprocess.run(
                    ["git", "-C", str(root), *args],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                return ""

        sha = git("rev-parse", "--short", "HEAD")
        if not sha:
            return  # no git at build time — leave version.py's plain fallback
        last_tag = git("describe", "--tags", "--match", "v*", "--abbrev=0")
        span = f"{last_tag}..HEAD" if last_tag else "HEAD"
        count = git("rev-list", "--count", span) or "0"
        out = root / "scripts" / "_build_info.py"
        out.write_text(f'BUILD_COMMIT = "{sha}"\nBUILD_NUMBER = "{count}"\n')
        # ensure the generated file lands in the wheel
        build_data.setdefault("force_include", {})[str(out)] = "scripts/_build_info.py"
