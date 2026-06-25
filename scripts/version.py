"""kas version string — packaged version + git build info.

Released installs report the packaged version ([project].version in pyproject).
A dev checkout additionally shows git build info — branch, commits since the last
release tag (the build number), short commit, and a -dirty flag — so you always
know exactly what's running. No version file to bump and no git hook: releases
are git tags (vX.Y.Z), and everything between is derived automatically.

    on a release tag (main):   0.1.0
    main, 3 commits past tag:  0.1.0+build.3.g1a2b3c4
    a feature branch:          0.1.0-v3.build.7.g9f8e7d6
    uncommitted changes:       ...g1a2b3c4.dirty
    installed, no git:         0.1.0
"""

import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

_FALLBACK = "0.1.0"  # only if BOTH importlib metadata and git are unavailable
_ROOT = Path(__file__).resolve().parent.parent


def _packaged() -> str:
    try:
        return _pkg_version("kas")
    except PackageNotFoundError:
        return _FALLBACK


def _git(*args: str) -> str | None:
    """Run git in the repo root; None if it fails or git/repo is absent."""
    try:
        r = subprocess.run(
            ["git", "-C", str(_ROOT), *args], capture_output=True, text=True, timeout=2
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def kas_version() -> str:
    base = _packaged()
    # Installed build (no checkout): just the packaged version.
    if _git("rev-parse", "--is-inside-work-tree") != "true":
        return base
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    sha = _git("rev-parse", "--short", "HEAD") or "?"
    # Build number = commits since the latest vX.Y.Z release tag (total commits
    # if no tags exist yet). Increments every commit; resets at each release tag.
    last_tag = _git("describe", "--tags", "--match", "v*", "--abbrev=0")
    span = f"{last_tag}..HEAD" if last_tag else "HEAD"
    count = _git("rev-list", "--count", span) or "0"
    dirty = ".dirty" if _git("status", "--porcelain") else ""
    # main: a clean release line; a feature branch: prefixed with the branch name.
    if branch == "main":
        if count == "0" and last_tag and not dirty:
            return base  # exactly on a release tag
        return f"{base}+build.{count}.g{sha}{dirty}"
    return f"{base}-{branch}.build.{count}.g{sha}{dirty}"
