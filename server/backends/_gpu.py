"""Process-wide GPU serialization — shared by EVERY backend.

There is one Metal device. Backends run GPU work on different threads: the MLX
text engine on its worker thread, the VLM engine directly in FastAPI's
threadpool. Without a single shared lock, two of them submit overlapping command
buffers and one can exceed the macOS GPU watchdog (~17s) — an UNCATCHABLE C++
abort (kIOGPUCommandBufferCallbackErrorTimeout) that kills the whole server.

Both the text and VLM engines hold this same lock for the duration of each
generation, so all GPU work across every model serializes (requests queue rather
than overlap). KAS_GPU_SERIALIZE=0 opts out (only safe with one resident model).
"""

import contextlib
import os
import threading

GPU_LOCK = threading.Lock()
SERIALIZE = os.environ.get("KAS_GPU_SERIALIZE", "1") != "0"


@contextlib.contextmanager
def gpu_guard():
    """Serialize GPU work across all engines (no-op if KAS_GPU_SERIALIZE=0)."""
    if SERIALIZE:
        with GPU_LOCK:
            yield
    else:
        yield
