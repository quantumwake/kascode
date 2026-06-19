"""Server configuration knobs (env-overridable)."""

import os

MODEL_ID = os.environ.get("KAS_MODEL", "mlx-community/Qwen3.6-27B-4bit")
DEFAULT_MAX_TOKENS = 8192
# Persist each thread's KV cache to disk (incremental deltas under the agent's
# session dir) so --resume rehydrates instead of cold-prefilling. Opt-in; the
# agent passes its session dir via the x-agent-session-dir header.
KV_PERSIST = os.environ.get("KAS_KV_PERSIST", "0") == "1"
