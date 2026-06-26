"""llama.cpp / GGUF inference backend (cross-platform: CPU + CUDA + ROCm + Metal +
Vulkan, depending on how llama-cpp-python was built). This is the portable path
for non-Apple hardware — one runtime covers NVIDIA and AMD and CPU.

Conforms to server.core.ports.EngineLike. It's a focused MVP: load + chat-template
tokenize + streaming generate + stats + the management ops. The token-level KV
warm-resume that the MLX backend implements (cache_snapshot / persist / rehydrate)
is intentionally a no-op here for now — recall still works, prefills are just cold.
That's the documented follow-up; this layer is validated on CPU CI + GPU CI
(Modal/RunPod) rather than on the Apple-only dev box, so the heavy import is
deferred and the runtime glue is kept standard.

Model resolution (model_id): a local *.gguf path, or a Hugging Face repo id (then
KAS_GGUF_FILE selects the quant file, default '*Q4_K_M.gguf'). GPU offload via
KAS_GPU_LAYERS (-1 = all layers, the default); context via KAS_CTX.
"""

import logging
import os
import threading
import time
from collections.abc import Iterator
from typing import Any

from ..core.ports import GenChunk

log = logging.getLogger("kas.llama_cpp")


class LlamaCppEngine:
    def __init__(self, model_id: str) -> None:
        try:
            from llama_cpp import Llama
        except ImportError as exc:  # the registry already gates on this; guard direct use
            raise RuntimeError(
                "the llama.cpp backend needs llama-cpp-python — install it (build with "
                "CUDA/ROCm/Metal for GPU): pip install llama-cpp-python"
            ) from exc

        self.model_id = model_id
        self.stats: dict[str, Any] = {"active": False}
        self.ping_count = 0
        self.last_ping_ts = 0.0
        self._cancel = threading.Event()
        self._lock = threading.Lock()  # llama.cpp Llama is not reentrant (single-stream)
        self._Llama = Llama
        self._load(model_id)

    # --- loading -------------------------------------------------------------

    def _load(self, model_id: str) -> None:
        from ..prompting import detect_dialect

        n_gpu_layers = int(os.environ.get("KAS_GPU_LAYERS", "-1"))  # -1 = offload all
        n_ctx = int(os.environ.get("KAS_CTX", "8192"))
        t0 = time.time()
        log.info("loading %s (n_gpu_layers=%s, n_ctx=%s) ...", model_id, n_gpu_layers, n_ctx)
        common = dict(n_gpu_layers=n_gpu_layers, n_ctx=n_ctx, verbose=False)
        if model_id.endswith(".gguf") and os.path.exists(model_id):
            self._llm = self._Llama(model_path=model_id, **common)
        else:  # Hugging Face repo id -> pick the quant file
            self._llm = self._Llama.from_pretrained(
                repo_id=model_id,
                filename=os.environ.get("KAS_GGUF_FILE", "*Q4_K_M.gguf"),
                **common,
            )
        self.model_id = model_id
        meta = getattr(self._llm, "metadata", {}) or {}
        self._chat_template = meta.get("tokenizer.chat_template")
        self.context_length = int(getattr(self._llm, "n_ctx", lambda: n_ctx)())
        self.n_layers = n_gpu_layers if n_gpu_layers >= 0 else None
        self.dialect = detect_dialect(self._chat_template)
        log.info("loaded in %.1fs (dialect: %s)", time.time() - t0, self.dialect.name)

    # --- tokenization --------------------------------------------------------

    def tokenize(
        self,
        chat_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
    ) -> list[int]:
        """Render the prompt via the GGUF's embedded chat template, then encode."""
        prompt = self._render_chat(chat_messages, tools, enable_thinking)
        return self._llm.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)

    def _render_chat(self, messages, tools, enable_thinking) -> str:
        if self._chat_template:
            try:
                from llama_cpp.llama_chat_format import Jinja2ChatFormatter

                meta = self._llm.metadata or {}
                fmt = Jinja2ChatFormatter(
                    template=self._chat_template,
                    bos_token=meta.get("tokenizer.ggml.bos_token", ""),
                    eos_token=meta.get("tokenizer.ggml.eos_token", ""),
                    add_generation_prompt=True,
                )
                kwargs = dict(getattr(self.dialect, "template_kwargs", {}))
                if tools:
                    kwargs["tools"] = tools
                return fmt(messages=messages, **kwargs).prompt
            except Exception as exc:  # bad/unknown template -> portable fallback
                log.warning("chat template render failed (%s); using plain fallback", exc)
        # Fallback: simple role-tagged concatenation (better than nothing).
        parts = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages]
        return "\n".join(parts) + "\nassistant:"

    def encode(self, text: str) -> list[int]:
        return self._llm.tokenize(text.encode("utf-8"), add_bos=False, special=False)

    def cache_snapshot(self, cache_key: str = "main") -> list[int]:
        return []  # MVP: no token-level KV warm-resume yet (documented follow-up)

    # --- generation ----------------------------------------------------------

    def generate(
        self,
        prompt_tokens: list[int],
        max_tokens: int,
        temperature: float | None,
        top_p: float | None,
        stop_sequences: list[str],
        cache_key: str = "main",
        persist_dir: str | None = None,
    ) -> Iterator[GenChunk]:
        with self._lock:
            self._cancel.clear()
            eos = self._llm.token_eos()
            t0 = time.time()
            gen_ids: list[int] = []
            text = ""
            finish: str | None = "length"
            stream = self._llm.generate(
                list(prompt_tokens),
                temp=0.0 if temperature is None else float(temperature),
                top_p=1.0 if top_p is None else float(top_p),
                reset=True,
            )
            for tok in stream:
                if self._cancel.is_set():
                    finish = "stop"
                    break
                if tok == eos:
                    finish = "stop"
                    break
                gen_ids.append(tok)
                whole = self._llm.detokenize(gen_ids).decode("utf-8", "replace")
                delta, text = whole[len(text) :], whole
                hit = next((s for s in stop_sequences if s and s in text), None)
                if hit:
                    cut = text.index(hit)
                    tail = text[len(text) - len(delta) : cut]
                    if tail:
                        yield GenChunk(text=tail)
                    finish = "stop_sequence"
                    break
                elapsed = max(1e-3, time.time() - t0)
                self.stats = {
                    "active": True,
                    "phase": "generating",
                    "tps": round(len(gen_ids) / elapsed, 1),
                    "processed": len(gen_ids),
                    "total": max_tokens,
                }
                if delta:
                    yield GenChunk(text=delta)
                if len(gen_ids) >= max_tokens:
                    finish = "length"
                    break
            self.stats = {"active": False}
            gen_tps = round(len(gen_ids) / max(1e-3, time.time() - t0), 1)
            yield GenChunk(
                text="",
                done=True,
                prompt_tokens=len(prompt_tokens),
                cached_tokens=0,
                generation_tokens=len(gen_ids),
                generation_tps=gen_tps,
                finish_reason=finish,
            )

    # --- management ----------------------------------------------------------

    def swap(self, model_id: str) -> None:
        with self._lock:
            try:
                self._llm.close()
            except Exception:
                pass
            self._load(model_id)

    def request_cancel(self) -> bool:
        active = bool(self.stats.get("active"))
        self._cancel.set()
        return active

    def ping_status(self) -> dict[str, Any]:
        self.ping_count += 1
        self.last_ping_ts = time.monotonic()
        age = round(time.monotonic() - self.last_ping_ts, 1) if self.last_ping_ts else None
        return {"pings": self.ping_count, "last_ping_age": age}

    def system_stats(self) -> dict[str, Any]:
        return {
            "layers": self.n_layers,
            "context_length": getattr(self, "context_length", None),
        }
