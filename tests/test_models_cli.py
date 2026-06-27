"""kas models: modality guessing from a Hub id, count humanizing, and search
result shaping (HfApi stubbed — no network).

Run:  uv run python tests/test_models_cli.py
"""

import sys
import types

sys.path.insert(0, ".")

from scripts import models

# guess_kind: id/tag/pipeline heuristics (we can't read config pre-download).
assert models.guess_kind("mlx-community/Qwen2.5-VL-7B-Instruct-4bit") == "vision"
assert models.guess_kind("openai/whisper-large-v3") == "stt"
assert models.guess_kind("black-forest-labs/FLUX.1-schnell") == "image"
assert models.guess_kind("BAAI/bge-small-en") == "embedding"
assert models.guess_kind("mlx-community/Qwen3-Coder-Next-4bit") == "text"
assert models.guess_kind("x/y", pipeline="automatic-speech-recognition") == "stt"
assert models.guess_kind("x/y", tags=["diffusers"]) == "image"
print("guess_kind: OK")

# _human_count
assert models._human_count(950) == "950"
assert models._human_count(212_100) == "212.1k"
assert models._human_count(3_400_000) == "3.4M"
assert models._human_count(0) == "0"
print("_human_count: OK")


# search_hub: shapes ModelInfo-ish objects, applies the gguf filter, sorts desc.
class MI:
    def __init__(self, id, downloads=0, likes=0, tags=None, pipeline_tag=None):
        self.id, self.downloads, self.likes = id, downloads, likes
        self.tags, self.pipeline_tag = tags, pipeline_tag


captured = {}


class FakeApi:
    def list_models(self, **kw):
        captured.update(kw)
        return [
            MI("mlx-community/A-4bit", downloads=10),
            MI("mlx-community/B-GGUF", downloads=999),
            MI("mlx-community/C-4bit", downloads=500),
        ]


models.__dict__.setdefault("huggingface_hub", None)
sys.modules["huggingface_hub"] = types.SimpleNamespace(HfApi=FakeApi)

# mlx bias -> filter="mlx"; results sorted by downloads desc
res = models.search_hub("qwen", limit=5, mlx=True, gguf=False)
assert captured["filter"] == "mlx" and captured["sort"] == "downloads" and captured["limit"] == 5
assert [r["id"] for r in res] == [
    "mlx-community/B-GGUF",
    "mlx-community/C-4bit",
    "mlx-community/A-4bit",
], res

# gguf filter keeps only ids containing 'gguf'
captured.clear()
res = models.search_hub("qwen", limit=5, mlx=False, gguf=True)
assert [r["id"] for r in res] == ["mlx-community/B-GGUF"], res
assert "filter" not in captured  # gguf is a post-filter, not an API filter
print("search_hub: OK")

# main() dispatch: unknown verb prints help (returns 0), search w/o query -> usage (1).
assert models.main(["search"]) == 1
print("main dispatch: OK")

print("all models-cli tests passed")
