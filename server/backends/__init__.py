"""Inference-backend registry + selector (OS/arch aware).

A backend is any class satisfying server.core.ports.EngineLike. MLX (Apple
silicon, via mlx_lm) is the first and currently only implementation; THIS is the
seam where other runtimes plug in — llama.cpp/GGUF (cross-platform CPU + CUDA /
ROCm / Metal), vLLM, etc. To add one: drop a module in server/backends/ whose
class implements EngineLike, register it in BACKENDS with a platform predicate,
and teach _detect_backend how to recognise its models. The core depends only on
EngineLike, never on a concrete backend, so nothing else changes.

Platform matters: a backend is tied to a runtime that only exists on some
OS/arch. MLX is built on Apple's Metal + Accelerate frameworks — `import mlx_lm`
fails outright on Linux/Windows or on x86. So each backend declares whether it
runs on the current host, and make_engine checks that BEFORE importing the
backend module — yielding a clear "not supported on this host" error instead of a
cryptic ImportError. Selection order: explicit `backend=` arg > KAS_BACKEND env >
auto-detect from the model id + platform. Loaders are lazy (imported only when a
supported backend is chosen).
"""

import importlib.util
import os
import platform
from collections.abc import Callable
from dataclasses import dataclass, field

from ..core.ports import EngineLike

# Type of a backend constructor: model_id -> an EngineLike instance.
EngineFactory = Callable[[str], EngineLike]


def _is_apple_silicon() -> bool:
    # MLX needs macOS (Darwin) on arm64 — its Metal/Accelerate deps don't exist
    # elsewhere, and mlx_lm won't even import off this combination.
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _load_mlx() -> EngineFactory:
    # Deferred import: the heavy MLX stack is pulled in only when MLX is both
    # supported and selected — guarded by Backend.supported() in make_engine.
    from .mlx import MlxEngine

    return MlxEngine


def _load_llama_cpp() -> EngineFactory:
    from .llama_cpp import LlamaCppEngine

    return LlamaCppEngine


def _has(module: str) -> Callable[[], bool]:
    # importable check WITHOUT importing (find_spec doesn't run the module).
    return lambda: importlib.util.find_spec(module) is not None


@dataclass(frozen=True)
class Backend:
    load: Callable[[], EngineFactory]  # lazy: returns the constructor
    supported: Callable[[], bool]  # does the current OS/arch support it?
    requires: str  # human note shown when it isn't supported / installed here
    installed: Callable[[], bool] = field(default=lambda: True)  # is its package present?


# The whole extension list. supported() gates on OS/arch (checked BEFORE import);
# installed() gates on the package being present. llama.cpp/GGUF is cross-platform
# (CPU + CUDA + ROCm + Metal, depending on how llama-cpp-python was built), so it's
# the portable path for non-Apple hardware.
BACKENDS: dict[str, Backend] = {
    "mlx": Backend(
        load=_load_mlx,
        supported=_is_apple_silicon,
        installed=_has("mlx_lm"),
        requires="macOS on Apple Silicon (arm64) with mlx-lm",
    ),
    "llama_cpp": Backend(
        load=_load_llama_cpp,
        supported=lambda: True,
        installed=_has("llama_cpp"),
        requires="llama-cpp-python (any OS; build with CUDA/ROCm/Metal for GPU)",
    ),
}


def available_backends() -> list[str]:
    """Backends that can actually run on this host (right OS/arch + installed)."""
    return sorted(name for name, b in BACKENDS.items() if b.supported() and b.installed())


def _detect_backend(model_id: str) -> str:
    """Best-effort backend guess from the model id AND the platform. Conservative:
    a GGUF id implies llama.cpp (cross-platform); otherwise prefer MLX on Apple
    Silicon. On a non-Apple host with a non-GGUF id we still return "mlx" so
    make_engine raises a clear platform error rather than silently guessing — when
    a CUDA/vLLM backend lands, prefer it here."""
    low = model_id.lower()
    if low.endswith(".gguf") or "gguf" in low:
        return "llama_cpp"  # GGUF -> llama.cpp (not yet implemented; see below)
    if _is_apple_silicon():
        return "mlx"
    return "mlx"


def make_engine(model_id: str, backend: str | None = None) -> EngineLike:
    """Build the inference backend for `model_id`, after checking this host can
    run it.

    Raises ValueError if the named backend isn't registered, or RuntimeError if it
    is registered but unsupported on this OS/arch (e.g. MLX on Linux) — both
    before any backend import, so the failure is a clear message, not an
    ImportError from deep inside a runtime.
    """
    name = backend or os.environ.get("KAS_BACKEND") or _detect_backend(model_id)
    b = BACKENDS.get(name)
    if b is None:
        raise ValueError(
            f"inference backend {name!r} is not available "
            f"(have: {', '.join(sorted(BACKENDS))}). Set KAS_BACKEND to one of "
            "those, or add the backend under server/backends/."
        )
    if not b.supported():
        here = f"{platform.system()}/{platform.machine()}"
        usable = ", ".join(available_backends()) or "none yet on this platform"
        raise RuntimeError(
            f"backend {name!r} needs {b.requires}, but this host is {here}. "
            f"Set KAS_BACKEND to a supported backend ({usable})."
        )
    if not b.installed():  # supported on this OS/arch, but its package isn't here
        raise RuntimeError(
            f"backend {name!r} is supported on this host but not installed — needs "
            f"{b.requires}. Install it, or set KAS_BACKEND to an installed backend "
            f"({', '.join(available_backends()) or 'none yet'})."
        )
    return b.load()(model_id)  # lazy-import the chosen backend, then construct
