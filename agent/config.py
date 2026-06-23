"""Agent configuration: env-overridable knobs, server probes, and small shared
helpers. Values here are mutated by the CLI composition root (agent/cli.py)
from parsed args at startup, so other modules read them as `config.MODEL` etc.
rather than importing the values by name (which would freeze them at import).
"""

import os

import httpx

BASE_URL = os.environ.get("KAS_BASE_URL", "http://127.0.0.1:8765")
MODEL = os.environ.get("KAS_MODEL")  # default: ask the server what it loaded
MAX_TOKENS = int(os.environ.get("KAS_MAX_TOKENS", "16384"))
# Compaction is a decode-speed relief valve, not a context-window necessity —
# KV continuation makes prefill cheap and quantization eases long-context
# decode, so trigger it rarely and high. Too low + a large project = a
# compact->read->compact thrash that never makes progress.
COMPACT_AT = int(os.environ.get("KAS_COMPACT_AT", "120000"))
# Hard floor on turns between compactions — guarantees no tight loop even if
# the work keeps refilling context.
COMPACT_COOLDOWN = int(os.environ.get("KAS_COMPACT_COOLDOWN", "5"))
# Decode-rate trigger: compaction exists to relieve slow decode, so trigger on
# the actual symptom. When smoothed decode tok/s drops below this, mark the
# session compactable (fires at the next safe boundary). 0 disables.
COMPACT_TPS = float(os.environ.get("KAS_COMPACT_TPS", "8.0"))

MAX_TOOL_OUTPUT = 8_000

# --- Opt-in image generation (--art): local mflux/FLUX backend -------------
# mflux's CLI is per-model and versioned, so every knob is env-tunable and the
# tool echoes the exact command it ran on failure (easy to correct / self-fix).
ART_BIN = os.environ.get("KAS_ART_BIN", "mflux-generate")
ART_MODEL = os.environ.get("KAS_ART_MODEL", "flux2-klein-4b")  # small, fast, fits beside the LLM
ART_STEPS = int(os.environ.get("KAS_ART_STEPS", "4"))  # distilled FLUX needs few steps
ART_QUANTIZE = os.environ.get("KAS_ART_QUANTIZE", "8")  # "" to disable
ART_OUTPUT_DIR = os.environ.get("KAS_ART_OUTPUT_DIR", "assets/generated")
# Consistency levers (see docs): a style preamble prepended to EVERY prompt so a
# whole sprite set shares look/angle/scale, plus LoRA files (path[,path]) for a
# locked style. Pair with a fixed `seed` per asset.
ART_STYLE = os.environ.get("KAS_ART_STYLE", "")
ART_LORAS = [p for p in os.environ.get("KAS_ART_LORAS", "").split(os.pathsep) if p]


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    return text[:MAX_TOOL_OUTPUT] + f"\n... [truncated {len(text) - MAX_TOOL_OUTPUT} chars]"


def served_model(base_url: str) -> str | None:
    """Ask the server which model it actually has loaded."""
    return served_info(base_url)[0]


def served_info(base_url: str) -> tuple[str | None, int | None]:
    """Return (model_id, context_length) from the server, or (None, None)."""
    try:
        d = httpx.get(base_url.rstrip("/") + "/v1/models", timeout=5).json()["data"][0]
        return d.get("id"), d.get("context_length")
    except Exception:
        return None, None
