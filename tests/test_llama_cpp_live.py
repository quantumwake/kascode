"""Live llama.cpp backend smoke (CPU): load a small GGUF, generate, and exercise
KV warm-resume — persist -> a fresh engine -> rehydrate -> the restored tokens
match, and the model-id guard refuses a different model.

Self-skips unless llama-cpp-python is installed AND KAS_TEST_GGUF points at a
.gguf, so it never runs in the normal suite (no SystemExit -> the characterization
runner stays green). Driven by .github/workflows/llama-cpp.yml.

Run:  KAS_TEST_GGUF=/path/to/model.gguf uv run python tests/test_llama_cpp_live.py
"""

import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, ".")


def _main() -> None:
    from server.backends.llama_cpp import LlamaCppEngine

    model = os.environ["KAS_TEST_GGUF"]
    eng = LlamaCppEngine(model)

    # tokenize a chat turn via the GGUF's embedded template, then generate
    toks = eng.tokenize([{"role": "user", "content": "Say hello in one word."}])
    assert toks and isinstance(toks[0], int), toks
    chunks = list(eng.generate(toks, max_tokens=8, temperature=0.0, top_p=1.0, stop_sequences=[]))
    text = "".join(c.text for c in chunks)
    assert chunks[-1].done and chunks[-1].generation_tokens > 0, chunks[-1]
    assert eng.cache_snapshot(), "cache should hold prompt + generated tokens"
    print("load + tokenize + generate + cache_snapshot: OK ->", repr(text[:40]))

    # persist -> fresh engine -> rehydrate roundtrip
    d = tempfile.mkdtemp()
    list(
        eng.generate(
            toks, max_tokens=4, temperature=0.0, top_p=1.0, stop_sequences=[], persist_dir=d
        )
    )
    snap = eng.cache_snapshot()
    eng2 = LlamaCppEngine(model)
    status = eng2.rehydrate("main", d)
    assert status.startswith("rehydrated"), status
    assert eng2.cache_snapshot() == snap, "restored KV tokens must match what was saved"
    print("KV persist + rehydrate roundtrip: OK ->", status)

    # model-id guard: a different model must NOT restore (KV is model-specific)
    eng2.model_id = "some-other-model"
    assert not eng2.rehydrate("main", d).startswith("rehydrated"), "model switch must cold-prefill"
    print("model-id guard (no cross-model restore): OK")
    print("all llama.cpp live tests passed")


if importlib.util.find_spec("llama_cpp") is None or not os.environ.get("KAS_TEST_GGUF"):
    print("test_llama_cpp_live: skipped (need llama-cpp-python + KAS_TEST_GGUF=<model.gguf>)")
else:
    _main()
