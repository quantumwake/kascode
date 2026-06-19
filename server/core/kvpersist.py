"""On-disk KV-cache persistence layout (pure path/sequence/metadata logic).

A thread's growing KV cache is persisted as a *directory of incremental delta
files* under the agent's session directory:

    <session-dir>/kvcache/<thread>/
        0000.safetensors   # KV for token positions [start, end) of this step
        0001.safetensors   # ... the next step's delta, appended
        ...
        tokens.json        # the full raw token stream (rewritten each step)
        memo.json          # the continuation memo (rewritten each step)

Each delta file is small (one turn's new positions), so persisting every
checkpoint is cheap — no GB-scale rewrites. On resume the deltas are replayed
in sequence order to rebuild the cache; tokens.json + memo.json restore the raw
stream + continuation state so the first resumed turn can actually hit the cache
(not just hold it). The actual array (de)serialization is done by the engine
(it's MLX/GPU-bound); everything here is pure and unit-testable.
"""

import json
import pathlib
import re

_SEQ_RE = re.compile(r"^(\d+)\.safetensors$")


def thread_dir(session_dir, thread: str) -> pathlib.Path:
    return pathlib.Path(session_dir) / "kvcache" / thread


def delta_files(dir_: pathlib.Path) -> list[pathlib.Path]:
    """Existing delta files, ordered by sequence number."""
    if not dir_.exists():
        return []
    out = []
    for p in dir_.iterdir():
        m = _SEQ_RE.match(p.name)
        if m:
            out.append((int(m.group(1)), p))
    return [p for _, p in sorted(out)]


def next_seq(dir_: pathlib.Path) -> int:
    files = delta_files(dir_)
    if not files:
        return 0
    return int(_SEQ_RE.match(files[-1].name).group(1)) + 1


def delta_path(dir_: pathlib.Path, seq: int) -> pathlib.Path:
    return dir_ / f"{seq:04d}.safetensors"


def write_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)  # atomic-ish: never leave a half-written sidecar


def read_json(path: pathlib.Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def tokens_path(dir_: pathlib.Path) -> pathlib.Path:
    return dir_ / "tokens.json"


def memo_path(dir_: pathlib.Path) -> pathlib.Path:
    return dir_ / "memo.json"
