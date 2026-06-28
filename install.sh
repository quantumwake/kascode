#!/bin/sh
# Install kas (and kas-server) as global commands via uv.
#
#   local clone:  ./install.sh
#   remote:       curl -fsSL https://raw.githubusercontent.com/quantumwake/kas/main/install.sh | sh
#
# uv provides the isolated Python env AND a pinned interpreter, so the install
# resolves identically everywhere. The agent (kas) is cross-platform; the MLX
# inference backend (kas-server) is Apple-Silicon only, and mlx-lm carries a
# platform marker, so installing on other hardware pulls the agent only — no
# Apple packages — and you point it at a remote server with --base-url.
set -eu

REPO="git+https://github.com/quantumwake/kas"   # https: works for public + gh-authed private
PYVER="3.11"

say() { printf '%s\n' "$*"; }

# --- requirement checks ---------------------------------------------------
say "kas installer -- checking requirements..."

case "$(uname -s)/$(uname -m)" in
    Darwin/arm64) say "  ok: macOS / Apple Silicon — MLX server backend will be installed" ;;
    *) say "  note: $(uname -s)/$(uname -m) is not Apple Silicon — the MLX backend is skipped (no Apple packages). The agent installs and runs against a remote --base-url." ;;
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

# --- optional capabilities -------------------------------------------------
# kas runs as a uv tool; `uv tool install --force` replaces the bundled package
# set, so feature packages are bundled via `--with` to persist them. Precedence:
#   KAS_WITH (explicit)  >  the saved set from a prior `kas doctor --install`
#   (~/.kascode/features.json — read directly so `curl | sh` needs no repo)  >
#   a light default. Add heavy ones later with `kas doctor --install`.
read_saved_features() {
    python3 - <<'PY' 2>/dev/null || true
import json, pathlib
try:
    print(" ".join(json.loads((pathlib.Path.home()/".kascode"/"features.json").read_text()).get("with", [])))
except Exception:
    pass
PY
}
case "$(uname -s)/$(uname -m)" in
    Darwin/arm64) DEFAULT_WITH="mlx-whisper sqlite-vec model2vec pillow ddgs trafilatura" ;;
    *)            DEFAULT_WITH="sqlite-vec model2vec pillow ddgs trafilatura" ;;
esac
WITH_PKGS="${KAS_WITH-$(read_saved_features)}"
[ -z "$WITH_PKGS" ] && WITH_PKGS="$DEFAULT_WITH"
WITH_FLAGS=""
for p in $WITH_PKGS; do WITH_FLAGS="$WITH_FLAGS --with $p"; done
[ -n "$WITH_PKGS" ] && say "  bundling features: $WITH_PKGS"

# --- install --------------------------------------------------------------
SELF="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)"
# --refresh: bypass any stale git/resolution entries a prior failed run left
# in uv's cache (the classic "fixed the source but install still fails" case).
if [ -n "${SELF:-}" ] && [ -f "${SELF}/pyproject.toml" ]; then
    say "installing kas from local checkout (${SELF}), editable, python ${PYVER}..."
    uv tool install --force --refresh --python "$PYVER" $WITH_FLAGS --editable "$SELF"
else
    say "installing kas from ${REPO}, python ${PYVER}..."
    uv tool install --force --refresh --python "$PYVER" $WITH_FLAGS "$REPO"
fi
uv tool update-shell 2>/dev/null || true

say ""
if command -v kas >/dev/null 2>&1; then
    say "OK: installed -> $(command -v kas) (+ kas-server)"
    say ""
    # Platform-aware capability check: detect GPU/peripherals and report what each
    # optional feature (vision, voice, TTS, image-gen, memory) needs on THIS host.
    say "checking optional capabilities for your platform..."
    say ""
    kas doctor 2>/dev/null || say "  (run \`kas doctor\` anytime for the capability report)"
    say ""
    say "  kas doctor --install   # guided install of the missing pieces above"
    say "  kas serve              # start the inference server (daemon)"
    say "  kas                    # launch the agent"
    say "  kas --help"
else
    say "OK: installed. Add uv's bin to PATH, then restart your shell:"
    say "    uv tool update-shell"
    say "  then: kas doctor   # platform capability report + guided install"
fi
say ""
say "(if a stale uv cache ever causes a repeat failure: uv cache clean && re-run)"
