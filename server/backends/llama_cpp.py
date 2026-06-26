"""llama.cpp / GGUF inference backend (cross-platform: CPU + CUDA + ROCm + Metal +
Vulkan, depending on how llama-cpp-python was built). This is the portable path
for non-Apple hardware — one runtime covers NVIDIA and AMD and CPU.

Conforms to server.core.ports.EngineLike: load + chat-template tokenize + streaming
generate + stats + management, plus KV warm-resume via llama.cpp's OWN state files
(in-memory prefix reuse between turns; llama_state_seq_save_file/load_file across a
restart, model-id guarded). The heavy import is deferred and the runtime glue is
kept standard + best-effort (any KV failure falls back to a cold prefill, never a
broken turn); the runtime path is validated on CPU CI + GPU CI (Modal/RunPod)
rather than on the Apple-only dev box.

Model resolution (model_id): a local *.gguf path, or a Hugging Face repo id (then
KAS_GGUF_FILE selects the quant file, default '*Q4_K_M.gguf'). GPU offload via
KAS_GPU_LAYERS (-1 = all layers, the default); context via KAS_CTX.
"""

import json
import logging
import os
import pathlib
import threading
import time
from collections.abc import Iterator
from typing import Any

from ..core.cache import longest_common_prefix
from ..core.ports import GenChunk

log = logging.getLogger("kas.llama_cpp")


def _kv_paths(persist_dir: str, thread: str) -> tuple[pathlib.Path, pathlib.Path]:
    d = pathlib.Path(persist_dir) / "kvcache" / thread
    return d / "kv.bin", d / "meta.json"


def kv_restore_plan(persist_dir: str, thread: str, model_id: str) -> tuple[bool, str]:
    """Pure pre-check for rehydrate (unit-testable without llama.cpp): is there a
    saved KV for this thread, and was it built with the SAME model? A KV cache is
    model-specific, so restoring across a model switch would be garbage — guard it."""
    kv, meta = _kv_paths(persist_dir, thread)
    if not kv.exists() or not meta.exists():
        return False, "no saved KV — cold prefill"
    try:
        saved = json.loads(meta.read_text()).get("model")
    except (OSError, json.JSONDecodeError):
        return False, "unreadable KV meta — cold prefill"
    if saved != model_id:
        return False, f"model changed ({saved} != {model_id}) — cold prefill"
    return True, "ok"


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
        self._cached_tokens: list[int] = []  # tokens currently held in the KV cache
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
        self._cached_tokens = []  # a (re)load invalidates any prior KV
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
        """Tokens currently held in the KV cache (for prefix reuse + persistence)."""
        return list(self._cached_tokens)

    # --- generation ----------------------------------------------------------

    def _token_viz(self, tok: int) -> dict | None:
        """Per-token logprob summary for /viz from llama.cpp's last-step logits.
        Best-effort (numpy over the vocab); any failure -> None so generation is
        never affected. Same shape as the MLX backend, so the client is backend-
        agnostic."""
        try:
            import numpy as np

            scores = getattr(self._llm, "scores", None)
            if scores is None:
                scores = getattr(self._llm, "_scores", None)
            row = max(0, int(getattr(self._llm, "n_tokens", 1)) - 1)
            logits = np.asarray(scores[row], dtype="float64")
            if logits.ndim != 1 or logits.size == 0:
                return None
            p = np.exp(logits - logits.max())
            p /= p.sum()
            conf = float(p[tok])
            entropy = float(-(p * np.log(p + 1e-12)).sum())
            idx = np.argpartition(-p, 5)[:5]
            idx = idx[np.argsort(-p[idx])]
            top = [
                [self._llm.detokenize([int(i)]).decode("utf-8", "replace"), float(p[int(i)])]
                for i in idx
            ]
            return {"conf": conf, "entropy": entropy, "top": top}
        except Exception:
            return None

    def generate(
        self,
        prompt_tokens: list[int],
        max_tokens: int,
        temperature: float | None,
        top_p: float | None,
        stop_sequences: list[str],
        cache_key: str = "main",
        persist_dir: str | None = None,
        viz: bool = False,
    ) -> Iterator[GenChunk]:
        with self._lock:
            self._cancel.clear()
            eos = self._llm.token_eos()
            t0 = time.time()
            gen_ids: list[int] = []
            text = ""
            finish: str | None = "length"
            full = list(prompt_tokens)
            # Reuse the KV prefix shared with the last request (append-only
            # transcripts share a long head): reset only when nothing overlaps, so
            # llama.cpp re-evals just the new suffix instead of the whole prompt.
            cached = longest_common_prefix(self._cached_tokens, full)
            stream = self._llm.generate(
                full,
                temp=0.0 if temperature is None else float(temperature),
                top_p=1.0 if top_p is None else float(top_p),
                reset=(cached == 0),
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
                tok_viz = self._token_viz(tok) if viz else None
                hit = next((s for s in stop_sequences if s and s in text), None)
                if hit:
                    cut = text.index(hit)
                    tail = text[len(text) - len(delta) : cut]
                    if tail:
                        yield GenChunk(text=tail, viz=tok_viz)
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
                    yield GenChunk(text=delta, viz=tok_viz)
                if len(gen_ids) >= max_tokens:
                    finish = "length"
                    break
            self.stats = {"active": False}
            # The cache now holds the prompt + every generated token except the
            # last (never fed back) — mirrors the MLX backend's accounting.
            self._cached_tokens = full + gen_ids[:-1] if gen_ids else full
            if persist_dir and not self._cancel.is_set():
                self._persist(cache_key, persist_dir)
            gen_tps = round(len(gen_ids) / max(1e-3, time.time() - t0), 1)
            yield GenChunk(
                text="",
                done=True,
                prompt_tokens=len(prompt_tokens),
                cached_tokens=cached,
                generation_tokens=len(gen_ids),
                generation_tps=gen_tps,
                finish_reason=finish,
            )

    # --- KV persistence (warm --resume; llama.cpp's own state files) ---------
    # Best-effort, like the MLX backend: any failure -> no persistence, never a
    # broken turn. llama.cpp serializes its OWN KV (ggml tensors in the context)
    # via llama_state_seq_save_file/load_file — a different format from MLX's
    # safetensors deltas, because the caches live in different memory. Full
    # snapshot per save (vs MLX's incremental deltas), but the restore is a fast
    # memcpy, so --resume fills the cache instantly instead of cold-prefilling.

    def _persist(self, thread: str, persist_dir: str) -> None:
        try:
            import llama_cpp

            kv, meta = _kv_paths(persist_dir, thread)
            kv.parent.mkdir(parents=True, exist_ok=True)
            toks = self._cached_tokens
            arr = (llama_cpp.llama_token * len(toks))(*toks)
            ctx = self._llm._ctx.ctx
            llama_cpp.llama_state_seq_save_file(ctx, str(kv).encode(), 0, arr, len(toks))
            meta.write_text(json.dumps({"model": self.model_id, "n": len(toks)}))
        except Exception:
            log.info("kv persist failed; next resume will cold-prefill", exc_info=True)

    def rehydrate(self, thread: str, persist_dir: str) -> str:
        """Restore this thread's KV from disk IF it was saved with the same model
        (a KV cache is model-specific). Returns a status string; the HTTP layer
        only treats a 'rehydrated …' prefix as a cache hit."""
        ok, reason = kv_restore_plan(persist_dir, thread, self.model_id)
        if not ok:
            return reason
        try:
            import ctypes

            import llama_cpp

            kv, meta = _kv_paths(persist_dir, thread)
            n = int(json.loads(meta.read_text())["n"])
            out = (llama_cpp.llama_token * n)()
            n_out = ctypes.c_size_t(0)
            ctx = self._llm._ctx.ctx
            llama_cpp.llama_state_seq_load_file(
                ctx, str(kv).encode(), 0, out, n, ctypes.byref(n_out)
            )
            self._cached_tokens = list(out[: n_out.value])
            self._llm.n_tokens = n_out.value  # tell the wrapper the cache is warm
            return f"rehydrated {n_out.value} KV tokens"
        except Exception:
            log.info("kv rehydrate failed; cold prefill", exc_info=True)
            self._cached_tokens = []
            return "rehydrate failed — cold prefill"

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
