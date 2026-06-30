"""Backend (llama.cpp / GGUF) dependency install, broken out PER ACCELERATOR.

Detects the GPU (cuda / rocm / metal / cpu) and installs llama-cpp-python built
for it, so the GPU build logic lives in ONE legible place instead of being smeared
through doctor.py and install.sh.

The fiddly bit that makes this its own module: uv caches the BUILT
llama-cpp-python wheel by sdist hash and IGNORES CMAKE_ARGS — so switching to a
GPU build silently reuses a prior CPU wheel. Every GPU builder therefore clears
that cache and forces a `--no-binary` source rebuild with the right CMAKE_ARGS.

Run:  python -m scripts.install_deps            # auto-detect + install for THIS env
      python -m scripts.install_deps --print     # show the command, don't run it
      python -m scripts.install_deps --gpu cuda   # force an accelerator
      python -m scripts.install_deps --python P   # target another interpreter's env
"""

import argparse
import platform
import re
import shlex
import shutil
import subprocess
import sys

# llama.cpp CMAKE flag per accelerator. `metal` is GGUF-on-Apple — MLX is the
# primary Apple backend, so llama.cpp isn't auto-installed there (None below).
LLAMACPP_CMAKE = {"cuda": "-DGGML_CUDA=on", "rocm": "-DGGML_HIP=on", "metal": "-DGGML_METAL=on"}


def detect_gpu() -> str:
    """Accelerator family: metal / cuda / rocm / cpu (mirrors doctor.detect_gpu)."""
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "metal"
    if shutil.which("nvidia-smi"):
        return "cuda"
    if shutil.which("rocminfo") or shutil.which("rocm-smi"):
        return "rocm"
    return "cpu"


def _llamacpp(python: str, cmake: str | None) -> list[str]:
    """Install command for llama-cpp-python into `python`'s env. With `cmake` set,
    a cache-cleared source build that links the GPU backend; else the plain wheel."""
    if not cmake:
        return ["uv", "pip", "install", "--python", python, "llama-cpp-python"]
    build = (
        "uv cache clean llama-cpp-python >/dev/null 2>&1; "
        f"CMAKE_ARGS={shlex.quote(cmake)} uv pip install --python {shlex.quote(python)} "
        "--no-binary llama-cpp-python --reinstall llama-cpp-python llama-cpp-python"
    )
    return ["sh", "-c", build]


def _cuda_tag() -> str:
    """abetlen's prebuilt-wheel tag for the host's CUDA (cu118 / cu121..cu125),
    capped at the highest published. Forward-compatible: a cu124 wheel runs on a
    newer 12.x runtime. Defaults to cu124 if nvcc isn't readable."""
    try:
        out = subprocess.run(
            ["nvcc", "--version"], capture_output=True, text=True, timeout=5
        ).stdout
        m = re.search(r"release (\d+)\.(\d+)", out)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            if major == 11:
                return "cu118"
            if major == 12:
                return f"cu12{min(minor, 5)}"
    except Exception:
        pass
    return "cu124"


def _has_cuda_check(python: str) -> str:
    """Shell test: exit 0 if the installed llama_cpp actually carries a CUDA lib."""
    py = (
        "import glob,pathlib,sys,llama_cpp as L; "
        "sys.exit(0 if glob.glob(str(pathlib.Path(L.__file__).parent/'lib'/'*cuda*')) else 1)"
    )
    return f"{shlex.quote(python)} -c {shlex.quote(py)}"


# --- one builder per accelerator -------------------------------------------


def install_deps_cuda(python: str) -> list[str]:
    """CUDA: try the prebuilt wheel FIRST (seconds), verify it really links the
    CUDA backend, and fall back to a from-source build (minutes) only if not.
    The verify matters because a plain index resolve can silently grab the CPU
    sdist; the source path also clears uv's CMAKE_ARGS-blind wheel cache."""
    tag = _cuda_tag()
    index = f"https://abetlen.github.io/llama-cpp-python/whl/{tag}"
    src = (
        "uv cache clean llama-cpp-python >/dev/null 2>&1; "
        f"CMAKE_ARGS={shlex.quote(LLAMACPP_CMAKE['cuda'])} uv pip install --python "
        f"{shlex.quote(python)} --no-binary llama-cpp-python --reinstall llama-cpp-python "
        "llama-cpp-python"
    )
    cmd = (
        f"echo 'trying prebuilt CUDA wheel ({tag})...'; "
        f"uv pip install --python {shlex.quote(python)} --reinstall llama-cpp-python "
        f"--extra-index-url {index} --index-strategy unsafe-best-match "
        "llama-cpp-python >/dev/null 2>&1 || true; "
        f"if {_has_cuda_check(python)}; then echo 'prebuilt CUDA wheel OK (no compile)'; "
        f"else echo 'no CUDA in wheel — building from source (a few minutes)...'; {src}; fi"
    )
    return ["sh", "-c", cmd]


def install_deps_rocm(python: str) -> list[str]:
    return _llamacpp(python, LLAMACPP_CMAKE["rocm"])


def install_deps_metal(python: str) -> None:
    # MLX is the primary backend on Apple Silicon (installed via the kas bundle);
    # llama.cpp/GGUF is optional there, so nothing to build by default.
    return None


def install_deps_cpu(python: str) -> list[str]:
    return _llamacpp(python, None)  # plain CPU GGUF backend


_DISPATCH = {
    "cuda": install_deps_cuda,
    "rocm": install_deps_rocm,
    "metal": install_deps_metal,
    "cpu": install_deps_cpu,
}


def backend_install_command(gpu: str | None = None, python: str | None = None):
    """(gpu, argv|None) — the llama.cpp backend install for the accelerator."""
    gpu = gpu or detect_gpu()
    return gpu, _DISPATCH[gpu](python or sys.executable)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="install_deps")
    ap.add_argument("--gpu", choices=list(_DISPATCH), help="force an accelerator")
    ap.add_argument("--python", default=sys.executable, help="target interpreter env")
    ap.add_argument("--print", action="store_true", dest="show", help="show, don't run")
    a = ap.parse_args(argv)
    gpu, cmd = backend_install_command(a.gpu, a.python)
    if cmd is None:
        print(f"[{gpu}] MLX is the backend here — no llama.cpp build needed.")
        return 0
    if gpu == "cuda":
        note = "GPU backend (prebuilt wheel if available, else a source compile)"
    elif gpu in LLAMACPP_CMAKE:
        note = "GPU backend (source compile, a few minutes)"
    else:
        note = "CPU backend"
    print(f"[{gpu}] llama.cpp {note}:\n  {' '.join(cmd)}")
    if a.show:
        return 0
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
