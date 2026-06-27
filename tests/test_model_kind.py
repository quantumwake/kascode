"""Model modality classification — keeps non-chat models (embeddings, STT,
diffusion) out of the chat picker while admitting text + vision LLMs.

Builds tiny fake HF snapshots so it needs no real models or network.

Run:  uv run python tests/test_model_kind.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from scripts.select_model import CHAT_KINDS, model_kind


def snap_with(tmp: Path, **files) -> Path:
    """Create a snapshot dir with the given files (config.json gets json-dumped)."""
    d = tmp / "snap"
    d.mkdir(exist_ok=True)
    for name, content in files.items():
        p = d / name
        p.write_text(json.dumps(content) if name.endswith(".json") else content)
    return d


CASES = {
    # arch-based
    ("config.json", "LlamaForCausalLM"): "text",
    ("config.json", "GptOssForCausalLM"): "text",
    ("config.json", "MistralForCausalLM"): "text",
    ("config.json", "WhisperForConditionalGeneration"): "stt",
    ("config.json", "BertModel"): "embedding",
    ("config.json", "MPNetForMaskedLM"): "embedding",
    ("config.json", "StaticModel"): "embedding",
}

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    for (fname, arch), want in CASES.items():
        snap = snap_with(tmp, **{fname: {"architectures": [arch], "model_type": "x"}})
        got = model_kind(snap)
        assert got == want, f"{arch}: wanted {want}, got {got}"
        for f in snap.iterdir():
            f.unlink()

    # vision: a causal/cond-gen arch WITH a vision_config -> vision (chat-capable)
    snap = snap_with(
        tmp,
        **{
            "config.json": {
                "architectures": ["Gemma4ForConditionalGeneration"],
                "vision_config": {},
            }
        },
    )
    assert model_kind(snap) == "vision", model_kind(snap)
    for f in snap.iterdir():
        f.unlink()

    # GGUF-companion config: model_type but no architectures -> text
    snap = snap_with(tmp, **{"config.json": {"model_type": "llama"}})
    assert model_kind(snap) == "text", model_kind(snap)
    for f in snap.iterdir():
        f.unlink()

    # diffusers pipeline (model_index.json, no config) -> image
    snap = snap_with(tmp, **{"model_index.json": {"_class_name": "StableDiffusionXLPipeline"}})
    assert model_kind(snap) == "image", model_kind(snap)
    for f in snap.iterdir():
        f.unlink()

    # bare GGUF weights repo (no config) -> text
    snap = snap_with(tmp, **{"model.gguf": ""})
    assert model_kind(snap) == "text", model_kind(snap)
    for f in snap.iterdir():
        f.unlink()

    # nothing recognizable -> other
    snap = snap_with(tmp, **{"tokenizer.json": {}})
    assert model_kind(snap) == "other", model_kind(snap)

# Only text + vision are chat-capable.
assert CHAT_KINDS == ("text", "vision")
print("model_kind: OK")
print("all model-kind tests passed")
