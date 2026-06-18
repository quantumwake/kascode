"""Server configuration knobs (env-overridable)."""

import os

MODEL_ID = os.environ.get("KAS_MODEL", "mlx-community/Qwen3.6-27B-4bit")
DEFAULT_MAX_TOKENS = 8192
