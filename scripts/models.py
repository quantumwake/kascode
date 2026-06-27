"""kas models — list local models, or search Hugging Face for new ones.

  kas models                  # list downloaded models, grouped by modality
  kas models list
  kas models search <query>   # search the Hub (MLX-biased on Apple Silicon)
  kas models search <q> --gguf | --all | --limit N
  kas models download <id>    # fetch the weights (progress)

Local listing reuses the picker's classifier (scripts.select_model); search hits
the Hub via huggingface_hub. Pure formatting (kind guess, count humanizer) is
unit-tested; the network calls are thin wrappers.
"""

import platform
import subprocess
import sys

from scripts.select_model import model_info


def _local_ids() -> set[str]:
    return {m["id"] for m in model_info()}


def _human_count(n: int) -> str:
    n = n or 0
    for unit, div in (("M", 1_000_000), ("k", 1_000)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(n)


def guess_kind(model_id: str, tags: list[str] | None = None, pipeline: str | None = None) -> str:
    """Best-effort modality from a Hub id + tags (we can't read config pre-download)."""
    s = model_id.lower()
    tagset = {t.lower() for t in (tags or [])}
    if "whisper" in s or pipeline == "automatic-speech-recognition":
        return "stt"
    if any(k in s for k in ("-vl", "vl-", "vision", "llava", "-vlm")) or "image-text-to-text" == (
        pipeline or ""
    ):
        return "vision"
    if any(k in s for k in ("flux", "sdxl", "stable-diffusion", "diffus")) or "diffusers" in tagset:
        return "image"
    if any(k in s for k in ("embed", "minilm", "mpnet", "bge-", "gte-", "nomic")):
        return "embedding"
    if pipeline in ("text-to-speech", "text-to-audio"):
        return "tts"
    return "text"


def cmd_list() -> int:
    rows = model_info()
    if not rows:
        print("no downloaded models — try:  kas models search <query>")
        return 0
    order = ["text", "vision", "embedding", "stt", "image", "other"]
    by_kind: dict[str, list] = {}
    for m in rows:
        by_kind.setdefault(m["kind"], []).append(m)
    print("downloaded models:")
    for kind in order:
        group = by_kind.get(kind)
        if not group:
            continue
        print(f"\n  {kind}")
        for m in sorted(group, key=lambda x: -x["size"]):
            tag = "" if m["complete"] else "  ⏳ partial"
            print(f"    {m['size_h']:>9}  {m['id']}{tag}")
    return 0


def search_hub(query: str, limit: int, mlx: bool, gguf: bool) -> list[dict]:
    """Return up to `limit` Hub models for `query`, most-downloaded first."""
    from huggingface_hub import HfApi

    # `sort="downloads"` returns most-downloaded first; `filter="mlx"` restricts to
    # the MLX library tag. (This huggingface_hub has no direction/library kwargs.)
    kwargs: dict = {"search": query, "sort": "downloads", "limit": limit}
    if mlx:
        kwargs["filter"] = "mlx"
    out = []
    for mi in HfApi().list_models(**kwargs):
        mid = mi.id
        if gguf and "gguf" not in mid.lower():
            continue
        out.append(
            {
                "id": mid,
                "downloads": getattr(mi, "downloads", 0) or 0,
                "likes": getattr(mi, "likes", 0) or 0,
                "kind": guess_kind(
                    mid, getattr(mi, "tags", None), getattr(mi, "pipeline_tag", None)
                ),
            }
        )
    return sorted(out, key=lambda r: -r["downloads"])


def cmd_search(args: list[str]) -> int:
    limit = 25
    mlx = gguf = allf = False
    terms = []
    it = iter(args)
    for a in it:
        if a == "--limit":
            limit = int(next(it, "25") or "25")
        elif a == "--mlx":
            mlx = True
        elif a == "--gguf":
            gguf = True
        elif a == "--all":
            allf = True
        else:
            terms.append(a)
    query = " ".join(terms).strip()
    if not query:
        print("usage: kas models search <query> [--mlx|--gguf|--all] [--limit N]")
        return 1
    # On Apple Silicon, bias to MLX unless the user widened it (--all/--gguf).
    apple = platform.machine() == "arm64" and platform.system() == "Darwin"
    if apple and not (mlx or gguf or allf):
        mlx = True
    try:
        results = search_hub(query, limit, mlx, gguf)
    except Exception as exc:
        print(f"search failed: {type(exc).__name__}: {exc}")
        return 1
    if not results:
        print(f"no models for {query!r}" + (" (try --all to widen beyond MLX)" if mlx else ""))
        return 0
    have = _local_ids()
    scope = "MLX" if mlx else ("GGUF" if gguf else "all")
    print(f"top {len(results)} for {query!r} ({scope}, by downloads):\n")
    for r in results:
        mark = "✓" if r["id"] in have else " "
        print(f"  {mark} {_human_count(r['downloads']):>6} ⭳  {r['id']}   [{r['kind']}]")
    print("\n  ✓ = already downloaded · get one:  kas models download <id>")
    return 0


def cmd_download(args: list[str]) -> int:
    if not args:
        print("usage: kas models download <model-id>")
        return 1
    model_id = args[0]
    print(f"downloading {model_id} …")
    # `hf download` gives reliable per-file progress bars; XET stalls, so disable it.
    try:
        return subprocess.run(
            ["hf", "download", model_id],
            env={**_env(), "HF_HUB_DISABLE_XET": "1"},
        ).returncode
    except FileNotFoundError:
        print("the `hf` CLI isn't on PATH (huggingface-hub should provide it)")
        return 1


def _env() -> dict:
    import os

    return dict(os.environ)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("list", "ls"):
        return cmd_list()
    if argv[0] == "search":
        return cmd_search(argv[1:])
    if argv[0] in ("download", "get", "pull"):
        return cmd_download(argv[1:])
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
