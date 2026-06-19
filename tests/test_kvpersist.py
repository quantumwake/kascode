"""Tests for the pure KV-persistence layout (paths, sequencing, ordered replay,
atomic sidecars). The MLX array (de)serialization is engine-side and GPU-bound,
so it's not exercised here.

Run:  uv run python tests/test_kvpersist.py
"""

import sys
import tempfile
import pathlib

sys.path.insert(0, ".")

from server.core import kvpersist as kv

with tempfile.TemporaryDirectory() as tmp:
    sess = pathlib.Path(tmp)
    d = kv.thread_dir(sess, "main")
    assert d == sess / "kvcache" / "main", d

    # empty dir: seq starts at 0, no files.
    assert kv.delta_files(d) == []
    assert kv.next_seq(d) == 0

    # create deltas out of lexical order; ordering is by numeric sequence.
    d.mkdir(parents=True)
    for seq in (0, 1, 2, 10):
        kv.delta_path(d, seq).write_text("x")
    files = kv.delta_files(d)
    assert [p.name for p in files] == ["0000.safetensors", "0001.safetensors",
                                       "0002.safetensors", "0010.safetensors"], files
    assert kv.next_seq(d) == 11, kv.next_seq(d)
    assert kv.delta_path(d, 11).name == "0011.safetensors"
    print("paths + sequencing: OK")

    # json sidecars: atomic write + tolerant read.
    kv.write_json(kv.tokens_path(d), [1, 2, 3, 4])
    assert kv.read_json(kv.tokens_path(d)) == [1, 2, 3, 4]
    kv.write_json(kv.memo_path(d), {"key": "abc", "finish": "stop"})
    assert kv.read_json(kv.memo_path(d))["finish"] == "stop"
    # missing / corrupt -> default, never raises.
    assert kv.read_json(d / "nope.json", default=None) is None
    (d / "bad.json").write_text("{not json")
    assert kv.read_json(d / "bad.json", default=[]) == []
    # no .tmp left behind after an atomic write.
    assert not list(d.glob("*.tmp")), list(d.glob("*.tmp"))
    print("json sidecars: OK")

print("all kvpersist tests passed")
