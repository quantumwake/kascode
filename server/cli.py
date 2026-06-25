"""kas-server — the local MLX inference server (Anthropic Messages API).

Installed as its own console script so `kas` (the agent/orchestrator) and the
server are separate binaries. `kas serve` manages this as a background daemon;
run `kas-server` directly to run it in the foreground.
"""

import argparse
import os


def main() -> None:
    import uvicorn

    from scripts.version import kas_version

    ap = argparse.ArgumentParser(prog="kas-server", description="kas inference server")
    ap.add_argument("--version", action="version", version=f"kas {kas_version()}")
    ap.add_argument("--port", type=int, default=int(os.environ.get("KAS_PORT", "8765")))
    ap.add_argument("--host", default=os.environ.get("KAS_HOST", "127.0.0.1"))
    ap.add_argument("--model", default=None, help="model repo to load")
    a = ap.parse_args()
    if a.model:
        os.environ["KAS_MODEL"] = a.model
    os.environ["KAS_PORT"] = str(a.port)
    uvicorn.run("server.app:app", host=a.host, port=a.port)


if __name__ == "__main__":
    main()
