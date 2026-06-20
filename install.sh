#!/bin/sh
# Install kas (and kas-server) as global commands via uv.
#
#   local clone:  ./install.sh
#   remote:       curl -fsSL https://raw.githubusercontent.com/quantumwake/kascode/main/install.sh | sh
#
# uv provides the isolated Python env AND a pinned interpreter, so the install
# resolves identically everywhere. kas is Apple-Silicon only (MLX).
set -eu

REPO="git+https://github.com/quantumwake/kascode"   # https: works for public + gh-authed private
PYVER="3.11"

say() { printf '%s\n' "$*"; }

# --- requirement checks ---------------------------------------------------
say "kas installer -- checking requirements..."

case "$(uname -s)/$(uname -m)" in
    Darwin/arm64) say "  ok: macOS / Apple Silicon" ;;
    *) say "  warning: kas-server needs macOS on Apple Silicon (MLX). $(uname -s)/$(uname -m) can still run the agent against a remote --base-url." ;;
esac

if command -v uv >/dev/null 2>&1; then
    say "  ok: uv $(uv --version 2>/dev/null | awk '{print $2}')"
else
    say "  installing uv (not found)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    . "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
fi

# uv fetches the pinned Python if the system lacks it -> consistent resolution
say "  ensuring Python $PYVER (uv-managed)..."
uv python install "$PYVER" >/dev/null 2>&1 || true

# --- install --------------------------------------------------------------
SELF="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)"
# --refresh: bypass any stale git/resolution entries a prior failed run left
# in uv's cache (the classic "fixed the source but install still fails" case).
if [ -n "${SELF:-}" ] && [ -f "${SELF}/pyproject.toml" ]; then
    say "installing kas from local checkout (${SELF}), editable, python ${PYVER}..."
    uv tool install --force --refresh --python "$PYVER" --editable "$SELF"
else
    say "installing kas from ${REPO}, python ${PYVER}..."
    uv tool install --force --refresh --python "$PYVER" "$REPO"
fi
uv tool update-shell 2>/dev/null || true

say ""
if command -v kas >/dev/null 2>&1; then
    say "OK: installed -> $(command -v kas) (+ kas-server)"
    say ""
    say "  kas serve        # start the inference server (daemon)"
    say "  kas              # launch the agent"
    say "  kas --help"
else
    say "OK: installed. Add uv's bin to PATH, then restart your shell:"
    say "    uv tool update-shell"
fi
say ""
say "(if a stale uv cache ever causes a repeat failure: uv cache clean && re-run)"
