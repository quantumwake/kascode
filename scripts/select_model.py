"""Interactive picker over locally downloaded HF models.

Prints the chosen model id to stdout (everything else goes to stderr) so it
composes with `make start MODEL=$(...)`.
"""

import pathlib
import sys

HUB = pathlib.Path.home() / ".cache" / "huggingface" / "hub"


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
        if not list(d.glob("snapshots/*/config.json")):
            continue  # not a loadable model (tokenizer-only or no config)
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
            }
        )
    return out


def downloaded_models() -> list[str]:
    return [m["id"] for m in model_info()]


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
