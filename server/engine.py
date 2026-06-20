"""MLX model wrapper: all MLX work runs on one dedicated thread.

MLX GPU streams are bound to the thread that creates them, and FastAPI serves
sync endpoints from a thread pool — so generation must never run on whichever
pool thread happens to handle the request ("There is no Stream(gpu, 1) in
current thread"). A single worker thread performs the mlx_lm import, the model
load, and every generation. This also serializes requests, which MLX requires
anyway.
"""

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .core.cache import longest_common_prefix

log = logging.getLogger("kas")

# Quantize the KV cache past this many tokens (full-attention layers dominate
# decode cost at long context; 8-bit KV halves their memory traffic with
# near-lossless quality). This compresses cache precision — it never drops
# or truncates context. Set KAS_KV_BITS="" to disable.
KV_BITS = int(os.environ.get("KAS_KV_BITS", "8") or 0) or None
KV_GROUP_SIZE = 64
MAX_CACHE_SLOTS = int(os.environ.get("KAS_CACHE_SLOTS", "4"))
# Below this, decode is fast anyway — keep full precision.
QUANTIZED_KV_START = int(os.environ.get("KAS_KV_START", "8192"))
# Emit a keep-alive chunk if the worker produces nothing for this long, so a
# long prefill (or a slow first token) never leaves the HTTP stream silent and
# trips the client's read timeout.
PING_SECONDS = float(os.environ.get("KAS_PING_SECONDS", "5"))


@dataclass
class GenChunk:
    text: str
    done: bool = False
    ping: bool = False  # keep-alive heartbeat (no content), not a real token
    prompt_tokens: int = 0  # full prompt length (for usage)
    cached_tokens: int = 0  # prefix served from the KV cache
    generation_tokens: int = 0
    prompt_tps: float = 0.0
    generation_tps: float = 0.0
    peak_memory: float = 0.0  # GB
    finish_reason: str | None = None  # "stop" | "length" | "stop_sequence"


class _Cancelled(Exception):
    """Raised from the prefill progress callback to abort an in-flight job.
    Prefill emits no tokens, so checking a flag between yields can't interrupt
    it — raising from the callback mlx_lm invokes during prefill can."""


class Engine:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._jobs: queue.Queue[tuple[queue.Queue, threading.Event, Callable]] = queue.Queue()
        self._active_cancel: "threading.Event | None" = None  # in-flight job's cancel flag
        self._ready = threading.Event()
        self._load_error: BaseException | None = None
        # Live generation stats, readable from any thread (GET /v1/stats).
        self.stats: dict[str, Any] = {"active": False}
        # Keep-alive ping bookkeeping (so clients can see pings are flowing).
        self.ping_count = 0
        self.last_ping_ts = 0.0  # time.monotonic() of the most recent ping
        self._thread = threading.Thread(target=self._worker, name="mlx-worker", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._load_error is not None:
            raise self._load_error

    # --- worker thread ----------------------------------------------------

    def _worker(self) -> None:
        try:
            # First mlx_lm import must happen on this thread so its GPU
            # generation stream is registered here.
            import mlx.core as mx
            from mlx_lm import load, stream_generate
            from mlx_lm.models.cache import (
                KVCache,
                can_trim_prompt_cache,
                make_prompt_cache,
                trim_prompt_cache,
            )

            self._KVCache = KVCache
            from mlx_lm.sample_utils import make_sampler

            self._stream_generate = stream_generate
            self._make_sampler = make_sampler
            self._make_prompt_cache = make_prompt_cache
            self._can_trim = can_trim_prompt_cache
            self._trim = trim_prompt_cache
            self._load = load
            self._mx = mx  # for KV-cache delta (de)serialization on this thread
            # One KV-cache slot per conversation thread (main + each subagent),
            # so switching threads restores that thread's cache instead of
            # resetting. LRU-bounded — local single GPU, only a few live at once.
            self._slots: dict[str, dict[str, Any]] = {}
            self._slot_order: list[str] = []
            mx.set_default_device(mx.gpu)
            # Pin weights in the GPU working set so macOS can't page them out
            # under memory pressure (matters for the 33 GB 8-bit quant).
            mx.set_wired_limit(mx.device_info()["max_recommended_working_set_size"])
            log.info("device: %s (metal=%s)", mx.default_device(), mx.metal.is_available())
            self._load_model(self.model_id)
        except BaseException as exc:
            self._load_error = exc
            self._ready.set()
            return
        self._ready.set()

        while True:
            out_q, cancel, produce = self._jobs.get()
            self._active_cancel = cancel  # exposed to request_cancel() + on_prefill
            try:
                for item in produce():
                    if cancel.is_set():
                        break
                    out_q.put(("item", item))
                out_q.put(("done", None))
            except BaseException as exc:  # propagate to the consumer
                out_q.put(("error", exc))
            finally:
                self._active_cancel = None

    def _load_model(self, model_id: str) -> None:
        """Worker-thread only: load (or swap to) a model and reset all state."""
        from .prompting import detect_dialect

        log.info("loading %s ...", model_id)
        t0 = time.time()
        self.model, self.tokenizer = self._load(model_id)
        self.model_id = model_id
        self.context_length = self._detect_context_length()
        try:
            self.n_layers = len(self._make_prompt_cache(self.model))  # one cache per layer
        except Exception:
            self.n_layers = None
        self.dialect = detect_dialect(getattr(self.tokenizer, "chat_template", None))
        self._slots = {}
        self._slot_order = []
        log.info("model loaded in %.1fs (dialect: %s)", time.time() - t0, self.dialect.name)

    def _detect_context_length(self) -> int | None:
        """Native context window (max_position_embeddings). Checked across the
        model and its sub-modules — MoE/multimodal models nest their args
        (e.g. A3B exposes it on model.language_model.args)."""
        candidates = [self.model, getattr(self.model, "language_model", None),
                      getattr(self.model, "model", None)]
        for obj in candidates:
            if obj is None:
                continue
            args = getattr(obj, "args", None) or getattr(obj, "config", None) or obj
            for attr in ("max_position_embeddings", "max_context_length", "context_length"):
                val = getattr(args, attr, None)
                if isinstance(val, int) and val > 0:
                    return val
            text = getattr(args, "text_config", None)
            val = getattr(text, "max_position_embeddings", None) if text else None
            if isinstance(val, int) and val > 0:
                return val
        return None

    def _slot(self, key: str) -> dict[str, Any]:
        slot = self._slots.get(key)
        if slot is None:
            if len(self._slot_order) >= MAX_CACHE_SLOTS:
                evict = self._slot_order.pop(0)
                self._slots.pop(evict, None)
                log.info("evicted cache slot %r (LRU)", evict)
            # append_only: has this thread only ever grown by append (no trim)?
            #   Continuation threads stay True and get KV quantized for free.
            # quantized: do the cache's full-attention layers hold quantized KV?
            #   (a quantized cache can't be trimmed — see reuse_cache).
            slot = {"cache": None, "tokens": [], "append_only": True, "quantized": False,
                    "saved_offset": 0}  # positions already persisted to disk (KV-resume)
            self._slots[key] = slot
        else:
            self._slot_order.remove(key)
        self._slot_order.append(key)  # most-recently-used last
        return slot

    def swap(self, model_id: str) -> None:
        """Swap the served model; blocks until loaded (or raises on failure)."""

        def produce() -> Iterator[str]:
            import mlx.core as mx

            old_model = self.model
            self.model = None
            del old_model
            mx.clear_cache()
            self._load_model(model_id)
            yield "ok"

        list(self._submit(produce))

    def request_cancel(self) -> bool:
        """Signal the in-flight job (if any) to stop — interrupts a long prefill
        (via the progress callback) and generation (between tokens). Callable
        from any thread; returns whether a job was active. Lets a client abort
        immediately instead of waiting for prefill to finish, which also frees
        the worker so a queued model swap can run."""
        c = self._active_cancel
        if c is not None:
            c.set()
            return True
        return False

    def _submit(self, produce: Callable[[], Iterator[Any]]) -> Iterator[Any]:
        out_q: queue.Queue = queue.Queue()
        cancel = threading.Event()
        self._jobs.put((out_q, cancel, produce))
        try:
            while True:
                try:
                    kind, payload = out_q.get(timeout=PING_SECONDS)
                except queue.Empty:
                    # worker still busy (e.g. long prefill) — heartbeat so the
                    # stream keeps flowing and read timeouts don't fire.
                    self.ping_count += 1
                    self.last_ping_ts = time.monotonic()
                    yield GenChunk(text="", ping=True)
                    continue
                if kind == "item":
                    yield payload
                elif kind == "error":
                    raise payload
                else:
                    return
        finally:
            cancel.set()  # client disconnected or finished: stop generating

    # --- public API ---------------------------------------------------------

    def tokenize(
        self,
        chat_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
    ) -> list[int]:
        return self.tokenizer.apply_chat_template(
            chat_messages,
            tools=tools,
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=enable_thinking,
            **getattr(self.dialect, "template_kwargs", {}),
        )

    def ping_status(self) -> dict[str, Any]:
        """Ping count and seconds since the last keep-alive ping (or None)."""
        age = round(time.monotonic() - self.last_ping_ts, 1) if self.last_ping_ts else None
        return {"pings": self.ping_count, "last_ping_age": age}

    def system_stats(self) -> dict[str, Any]:
        """Model + GPU stats for the /stats panel. Memory queries are cheap and
        read-only, so they're safe to call off the worker thread."""
        out: dict[str, Any] = {
            "layers": getattr(self, "n_layers", None),
            "context_length": getattr(self, "context_length", None),
        }
        try:
            mx = self._mx
            out["gpu_active_gb"] = round(mx.get_active_memory() / 1e9, 2)
            out["gpu_peak_gb"] = round(mx.get_peak_memory() / 1e9, 2)
        except Exception:
            pass
        return out

    def cache_snapshot(self, cache_key: str = "main") -> list[int]:
        """Tokens currently held by the named thread's KV cache."""
        slot = self._slots.get(cache_key)
        return list(slot["tokens"]) if slot else []

    def encode(self, text: str) -> list[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

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
        slot = self._slot(cache_key)

        def reuse_cache(full: list[int]) -> int:
            """Trim/reset this thread's KV cache to the longest shared prefix.

            Agent transcripts are append-only, so consecutive requests on the
            same thread share a long prefix — reusing it skips most prefill.
            """
            common = 0
            if slot["cache"] is not None:
                tokens = slot["tokens"]
                common = longest_common_prefix(tokens, full)
                excess = len(tokens) - common
                if excess > 0:
                    trimmed = (
                        common > 0
                        and self._can_trim(slot["cache"])
                        and self._trim(slot["cache"], excess) == excess
                    )
                    if trimmed:
                        # A live trim succeeded, so this thread genuinely uses
                        # the trimmable-cache path; stop quantizing it (a
                        # quantized cache can't be trimmed). Threads that only
                        # ever append (the continuation case) never reach here,
                        # so they keep quantizing exactly as before.
                        slot["append_only"] = False
                        slot["tokens"] = tokens[:common]
                    else:
                        # Rotated sliding window, or quantized (untrimmable)
                        # layers — must reset and re-prefill. Log when it's the
                        # quantization cliff so it's measurable, not silent.
                        if slot["quantized"]:
                            log.info(
                                "cache reset: %d-token trim needed but cache is "
                                "quantized (untrimmable) — full re-prefill", excess,
                            )
                        slot["cache"] = None
            if slot["cache"] is None:
                # Fresh cache: append-only again until a trim proves otherwise,
                # so post-reset threads resume quantizing like the original did.
                common = 0
                slot["cache"] = self._make_prompt_cache(self.model)
                slot["tokens"] = []
                slot["quantized"] = False
                slot["append_only"] = True
                slot["saved_offset"] = 0
                slot["persist_reset"] = True  # on-disk deltas are now stale
            return common

        def produce() -> Iterator[GenChunk]:
            sampler = self._make_sampler(
                temp=temperature if temperature is not None else 0.7,
                top_p=top_p if top_p is not None else 0.95,
            )
            full = list(prompt_tokens)
            cached = reuse_cache(full)
            emitted = ""
            last = None
            gen_ids: list[int] = []
            finish = "stop"
            cancelled = False
            t_start = time.time()

            def on_prefill(processed: int, total: int) -> None:
                # The only place a long prefill can be interrupted — mlx_lm calls
                # this during prefill chunking; raising aborts it.
                if self._active_cancel is not None and self._active_cancel.is_set():
                    raise _Cancelled()
                self.stats = {
                    "active": True,
                    "phase": "prefill",
                    "processed": int(processed),
                    "total": int(total),
                    "cached": cached,
                    "elapsed": round(time.time() - t_start, 1),
                }

            try:
                # Quantize ONLY the full-attention KVCache layers (the ones
                # whose reads grow with context). Do NOT pass kv_bits to
                # mlx_lm — its blanket path also tries to quantize Gemma-4's
                # RotatingKVCache layers, which raises "Quantization NYI".
                # Quantize ONLY append-only (continuation) threads: a quantized
                # KV cache can't be trimmed, so quantizing a thread that later
                # re-renders would force a full-context re-prefill on its next
                # trim. Append-only threads never trim, so this is free.
                if KV_BITS and slot["append_only"]:
                    converted = 0
                    for i, c in enumerate(slot["cache"]):
                        if isinstance(c, self._KVCache) and c.offset > QUANTIZED_KV_START:
                            slot["cache"][i] = c.to_quantized(
                                group_size=KV_GROUP_SIZE, bits=KV_BITS
                            )
                            converted += 1
                    if converted:
                        slot["quantized"] = True
                        log.info(
                            "quantized %d full-attention KV caches to %d-bit", converted, KV_BITS
                        )
                for resp in self._stream_generate(
                    self.model,
                    self.tokenizer,
                    full[cached:],
                    max_tokens=max_tokens,
                    sampler=sampler,
                    prompt_cache=slot["cache"],
                    prompt_progress_callback=on_prefill,
                ):
                    self.stats = {
                        "active": True,
                        "phase": "generate",
                        "generated": resp.generation_tokens,
                        "tps": round(resp.generation_tps, 1),
                        "cached": cached,
                        "elapsed": round(time.time() - t_start, 1),
                    }
                    last = resp
                    gen_ids.append(resp.token)
                    text = resp.text
                    emitted += text
                    # Manual stop-sequence handling (mlx_lm only stops on EOS).
                    hit = next((s for s in stop_sequences if s in emitted), None)
                    if hit is not None:
                        cut = emitted.index(hit)
                        overshoot = len(emitted) - cut
                        yield GenChunk(text=text[: max(0, len(text) - overshoot)])
                        finish = "stop_sequence"
                        break
                    yield GenChunk(text=text)
                else:
                    finish = (last.finish_reason if last else None) or "stop"
            except _Cancelled:
                cancelled = True
                finish = "cancelled"
            finally:
                if cancelled:
                    # Interrupted (often mid-prefill): the cache is partial and
                    # unusable — discard it so the next turn re-prefills cleanly.
                    slot["cache"] = None
                    slot["tokens"] = []
                    slot["saved_offset"] = 0
                else:
                    # The cache now holds the full prompt plus every generated
                    # token except the last (it was never fed back through).
                    slot["tokens"] = full + gen_ids[:-1]
                self.stats = {"active": False}
            if persist_dir and not cancelled:
                # Append this turn's KV delta to disk (worker thread → mlx-safe).
                self._persist_kv_delta(cache_key, slot, persist_dir)
            yield GenChunk(
                text="",
                done=True,
                prompt_tokens=len(full),
                cached_tokens=cached,
                generation_tokens=last.generation_tokens if last else 0,
                prompt_tps=last.prompt_tps if last else 0.0,
                generation_tps=last.generation_tps if last else 0.0,
                peak_memory=last.peak_memory if last else 0.0,
                finish_reason=finish,
            )

        return self._submit(produce)

    # --- KV-cache persistence (warm --resume) --------------------------------
    # Incremental: each turn appends only the new positions' KV to a numbered
    # delta file under <session>/kvcache/<thread>/, so writes are small. Restored
    # by replaying the deltas in order. Plain KVCache layers only — quantized /
    # rotating caches are skipped (resume falls back to a cold prefill), a known
    # follow-up. Everything here is best-effort: any failure → no persistence,
    # never a broken turn.

    def _persist_kv_delta(self, thread: str, slot: dict, persist_dir: str) -> None:
        try:
            from .core import kvpersist

            cache = slot.get("cache")
            if cache is None:
                return
            if not all(isinstance(c, self._KVCache) for c in cache):
                return  # quantized/rotating layers: delta-slice not supported yet
            d = kvpersist.thread_dir(persist_dir, thread)
            start = slot.get("saved_offset", 0)
            if slot.pop("persist_reset", False):
                import shutil

                shutil.rmtree(d, ignore_errors=True)  # stale deltas after a reset
                start = 0
            end = int(cache[0].offset)
            d.mkdir(parents=True, exist_ok=True)
            if end > start:
                arrays = {}
                for i, c in enumerate(cache):
                    k, v = c.state
                    arrays[f"{i}.k"] = k[:, :, start:end, :]
                    arrays[f"{i}.v"] = v[:, :, start:end, :]
                seq = kvpersist.next_seq(d)
                self._mx.save_safetensors(
                    str(kvpersist.delta_path(d, seq)), arrays,
                    metadata={"start": str(start), "end": str(end)},
                )
                slot["saved_offset"] = end
            kvpersist.write_json(kvpersist.tokens_path(d), slot["tokens"])
        except Exception as exc:  # never let persistence break generation
            log.info("kv persist skipped (%s): %s", thread, exc)

    def rehydrate(self, thread: str, persist_dir: str) -> str:
        """Replay on-disk KV deltas into the thread's slot (if cold). Returns a
        short status string. Best-effort: on any mismatch the slot is left cold
        and the next turn prefills normally."""

        def produce() -> Iterator[str]:
            from .core import kvpersist

            slot = self._slot(thread)
            if slot.get("cache") is not None and slot.get("tokens"):
                yield "warm"  # already in memory; nothing to load
                return
            try:
                d = kvpersist.thread_dir(persist_dir, thread)
                files = kvpersist.delta_files(d)
                tokens = kvpersist.read_json(kvpersist.tokens_path(d))
                if not files or not tokens:
                    yield "cold"
                    return
                cache = self._make_prompt_cache(self.model)
                if not all(isinstance(c, self._KVCache) for c in cache):
                    yield "cold (non-plain cache)"
                    return
                ks: list = [[] for _ in cache]
                vs: list = [[] for _ in cache]
                for f in files:
                    arr = self._mx.load(str(f))
                    for i in range(len(cache)):
                        ks[i].append(arr[f"{i}.k"])
                        vs[i].append(arr[f"{i}.v"])
                for i, c in enumerate(cache):
                    c.state = (self._mx.concatenate(ks[i], axis=2),
                               self._mx.concatenate(vs[i], axis=2))
                slot["cache"] = cache
                slot["tokens"] = list(tokens)
                slot["saved_offset"] = int(cache[0].offset)
                slot["append_only"] = True
                slot["quantized"] = False
                log.info("kv rehydrate: restored %d tokens for %r", cache[0].offset, thread)
                yield f"rehydrated {cache[0].offset}"
            except Exception as exc:
                log.info("kv rehydrate failed (cold) for %r: %s", thread, exc)
                slot["cache"] = None
                slot["tokens"] = []
                slot["saved_offset"] = 0
                yield "cold"

        return (list(self._submit(produce)) or ["cold"])[-1]
