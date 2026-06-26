"""Backend selection (server/backends): OS/arch-aware routing, exercised without
loading a real model. Verifies the registry, model-id+platform detection, and
the clear errors for an unknown or platform-unsupported backend (e.g. MLX off
Apple Silicon). No model/GPU/server needed.

Run:  uv run python tests/test_backends.py
"""

import platform
import sys

sys.path.insert(0, ".")

import server.backends as be
from server.backends import Backend, _detect_backend, available_backends, make_engine

# --- detection from model id + platform ------------------------------------
assert _detect_backend("mlx-community/Qwen3.6-27B-4bit") == "mlx"
assert _detect_backend("TheBloke/Llama-2-7B-GGUF") == "llama_cpp"
assert _detect_backend("model.gguf") == "llama_cpp"
print("detect: OK")

# --- unknown backend -> ValueError naming the registry ---------------------
try:
    make_engine("whatever", backend="does-not-exist")
    raise AssertionError("unknown backend should raise")
except ValueError as e:
    assert "not available" in str(e), e
print("unknown backend: OK")


# --- registered but UNSUPPORTED here -> RuntimeError, and load() never runs --
def _boom() -> object:
    raise AssertionError("make_engine must not import an unsupported backend")


be.BACKENDS["faux"] = Backend(load=_boom, supported=lambda: False, requires="a GPU we lack")
try:
    make_engine("m", backend="faux")
    raise AssertionError("unsupported backend should raise")
except RuntimeError as e:
    assert "this host is" in str(e), e
finally:
    be.BACKENDS.pop("faux", None)
print("unsupported backend (no import): OK")

# --- registered + supported -> load() runs and constructs ------------------
_built: dict[str, str] = {}


def _fake_factory(model_id: str) -> object:
    _built["id"] = model_id
    return object()


be.BACKENDS["faux2"] = Backend(load=lambda: _fake_factory, supported=lambda: True, requires="")
try:
    eng = make_engine("the-model", backend="faux2")
    assert eng is not None and _built["id"] == "the-model"
finally:
    be.BACKENDS.pop("faux2", None)
print("supported backend builds: OK")

# --- mlx is registered; available iff this host is Apple Silicon + installed -
assert "mlx" in be.BACKENDS
on_apple = platform.system() == "Darwin" and platform.machine() == "arm64"
import importlib.util

have_mlx = importlib.util.find_spec("mlx_lm") is not None
assert ("mlx" in available_backends()) == (on_apple and have_mlx)
print(f"platform routing (apple_silicon={on_apple}): OK")


# --- llama.cpp/GGUF: registered, cross-platform, package-gated --------------
assert "llama_cpp" in be.BACKENDS
lc = be.BACKENDS["llama_cpp"]
assert lc.supported() is True, "llama.cpp runs on any OS/arch"
have_llama = importlib.util.find_spec("llama_cpp") is not None
assert ("llama_cpp" in available_backends()) == have_llama
# supported here but the package is absent -> a clear 'not installed' error (no import)
if not have_llama:
    try:
        make_engine("model.gguf", backend="llama_cpp")
        raise AssertionError("uninstalled-but-supported backend should raise")
    except RuntimeError as e:
        assert "not installed" in str(e), e
# the backend module imports fine WITHOUT llama-cpp-python (deferred import)
import server.backends.llama_cpp as lcmod

assert hasattr(lcmod, "LlamaCppEngine")
print("llama.cpp registered + cross-platform + install-gated + deferred import: OK")


# --- KV warm-resume guard: only restore a cache built with the SAME model ---
# (pure pre-check, runtime-free — a KV cache is model-specific, so a model switch
# must cold-prefill, not restore garbage.)
import json
import pathlib
import tempfile

d = pathlib.Path(tempfile.mkdtemp())
ok, why = lcmod.kv_restore_plan(str(d), "main", "model-A")
assert not ok and "no saved KV" in why, why  # nothing saved yet
kvdir = d / "kvcache" / "main"
kvdir.mkdir(parents=True)
(kvdir / "kv.bin").write_bytes(b"\x00")
(kvdir / "meta.json").write_text(json.dumps({"model": "model-A", "n": 3}))
assert lcmod.kv_restore_plan(str(d), "main", "model-A")[0] is True, "same model -> restore"
ok2, why2 = lcmod.kv_restore_plan(str(d), "main", "model-B")
assert not ok2 and "model changed" in why2, why2  # switched model -> cold prefill
print("KV warm-resume model-id guard: OK")

print("all backend tests passed")
