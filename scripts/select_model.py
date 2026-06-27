"""Interactive picker over locally downloaded HF models.

Prints the chosen model id to stdout (everything else goes to stderr) so it
composes with `make start MODEL=$(...)`.
"""

import json
import pathlib
import sys

HUB = pathlib.Path.home() / ".cache" / "huggingface" / "hub"

# Model modalities. "chat" kinds (text + vision) are loadable in the /model
# picker; the rest power their own features (or nothing) and shouldn't clutter
# the chat selector.
CHAT_KINDS = ("text", "vision")


def model_kind(snap: pathlib.Path) -> str:
    """Classify a model snapshot by what it DOES, from its config.

    Returns one of: text (causal LM chat), vision (multimodal chat),
    embedding, stt (speech->text), image (diffusion text->image), or other.
    Keyed on config.json's `architectures` (the reliable signal); diffusers
    pipelines use model_index.json; GGUF repos (no config) fall back to name.
    """
    cfg = snap / "config.json"
    if cfg.exists():
        try:
            c = json.loads(cfg.read_text())
        except (OSError, json.JSONDecodeError):
            c = {}
        arch = (c.get("architectures") or [""])[0]
        mt = c.get("model_type", "")
        is_vision = "vision_config" in c or "vision_tower" in c or "vision" in mt
        if "Whisper" in arch or mt == "whisper":
            return "stt"
        if arch == "StaticModel" or mt == "model2vec":
            return "embedding"
        # Encoder-only (BERT/MPNet/RoBERTa) = sentence embeddings, not chat.
        if arch.endswith("ForMaskedLM") or (
            arch.endswith("Model")
            and "CausalLM" not in arch
            and "ConditionalGeneration" not in arch
        ):
            return "embedding"
        if is_vision and arch.endswith(("ForConditionalGeneration", "ForCausalLM")):
            return "vision"
        if arch.endswith(("ForCausalLM", "LMHeadModel", "ForConditionalGeneration")):
            return "text"
        # GGUF-companion configs often carry model_type but no architectures.
        if mt in (
            "llama", "mistral", "mixtral", "qwen2", "qwen3", "qwen3_next", "qwen3_5",
            "gemma", "gemma2", "gemma3", "phi", "phi3", "gpt_oss", "deepseek_v3",
            "kimi_k2", "apertus", "gpt_neox", "falcon", "cohere", "command-r",
        ):
            return "text"
        return "other"
    if (snap / "model_index.json").exists():
        return "image"  # diffusers text->image pipeline
    # No config: GGUF weight repo (tokenizer + *.gguf) — almost always an LLM.
    if list(snap.glob("*.gguf")):
        return "text"
    return "other"


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit in ("B", "KB") else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def model_info() -> list[dict]:
    """Downloaded models with on-disk size and whether the download is complete.

    Size sums the HF blob store; a download in progress leaves `*.incomplete`
    blobs, which marks the model partial.
    """
    out = []
    for d in sorted(HUB.glob("models--*")):
        snaps = sorted(d.glob("snapshots/*"))
        snap = snaps[-1] if snaps else None
        # Loadable = has weights/config of some kind; skip tokenizer-only dirs.
        if snap is None or not (
            (snap / "config.json").exists()
            or (snap / "model_index.json").exists()
            or list(snap.glob("*.gguf"))
        ):
            continue
        kind = model_kind(snap)
        blobs = d / "blobs"
        size, partial = 0, False
        if blobs.exists():
            for f in blobs.iterdir():
                if not f.is_file():
                    continue
                if f.name.endswith(".incomplete"):
                    partial = True  # download in progress
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
        # A dangling snapshot symlink = a file that was never pulled (interrupted
        # download), so the model is incomplete even with no .incomplete blob.
        if not partial:
            for snap in d.glob("snapshots/*"):
                if any(f.is_symlink() and not f.exists() for f in snap.rglob("*")):
                    partial = True
                    break
        out.append(
            {
                "id": d.name.removeprefix("models--").replace("--", "/"),
                "size": size,
                "size_h": _human(size),
                "complete": not partial,
                "kind": kind,
            }
        )
    return out


def downloaded_models(kinds: tuple[str, ...] | None = CHAT_KINDS) -> list[str]:
    """Model ids. Defaults to chat-capable (text + vision); pass kinds=None for all."""
    return [m["id"] for m in model_info() if kinds is None or m["kind"] in kinds]


def main() -> None:
    models = downloaded_models()
    if not models:
        print("no downloaded models found — run: make download MODEL=<id>", file=sys.stderr)
        sys.exit(1)
    print("downloaded models:", file=sys.stderr)
    info = {m["id"]: m for m in model_info()}
    for i, m in enumerate(models, 1):
        meta = info.get(m, {})
        tag = f"  [{meta.get('size_h', '?')}{'' if meta.get('complete', True) else ', partial'}]"
        print(f"  {i}) {m}{tag}", file=sys.stderr)
    try:
        raw = input("model #: ")
        choice = int(raw)
        if not 1 <= choice <= len(models):
            raise ValueError
    except (ValueError, EOFError):
        print("invalid selection", file=sys.stderr)
        sys.exit(1)
    print(models[choice - 1])


if __name__ == "__main__":
    main()
