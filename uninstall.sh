#!/bin/sh
# Uninstall kas (and kas-server).
#
#   local clone:  ./uninstall.sh           (or: make uninstall)
#   remote:       curl -fsSL https://raw.githubusercontent.com/quantumwake/kas/main/uninstall.sh | sh
#
# Removes the uv tool only. Your config/data under ~/.kascode and any downloaded
# model weights under ~/.cache/huggingface are LEFT IN PLACE (models are large
# and shared) — the script prints how to remove them, or set KAS_PURGE=1 to drop
# the kas config dir too.
set -eu

say() { printf '%s\n' "$*"; }

say "uninstalling kas..."
if command -v uv >/dev/null 2>&1; then
    if uv tool uninstall kas >/dev/null 2>&1; then
        say "  removed the kas tool (kas + kas-server)"
    else
        say "  kas was not installed as a uv tool (nothing to remove)"
    fi
else
    say "  uv not found — if kas was pip-installed, run: pip uninstall kas"
fi

CFG="$HOME/.kascode"
if [ -d "$CFG" ]; then
    say ""
    if [ "${KAS_PURGE:-}" = "1" ]; then
        rm -rf "$CFG" && say "  purged config + data: $CFG (KAS_PURGE=1)"
    else
        say "  config + data kept at $CFG (features.json, memory, sessions)."
        say "    remove it too:  rm -rf $CFG   (or re-run with KAS_PURGE=1)"
    fi
fi
say ""
say "  downloaded models are untouched at ~/.cache/huggingface/hub"
say "    (remove specific ones with:  kas models  …  or  hf cache delete)"
say "done."
