"""Head-to-head model benchmark: hot-swap each model and measure decode tok/s
at several context sizes + a tool round-trip. Usage:

    uv run python scripts/bench_models.py MODEL_A MODEL_B ...

Requires the server running (make start). Models must be downloaded.
"""

import sys
import time

import anthropic
import httpx

BASE = "http://127.0.0.1:8765"
client = anthropic.Anthropic(base_url=BASE, api_key="local", timeout=900, max_retries=0)

FILLER = "The quick brown fox jumps over the lazy dog by the river at dawn. " * 60  # ~1k tok


def swap(model: str) -> dict:
    return httpx.post(BASE + "/v1/models/select", json={"model": model}, timeout=1800).json()


def decode_tps(model: str, ctx_copies: int) -> tuple[int, float]:
    """Generate a fixed-length answer after a prompt of ~ctx_copies*1k tokens."""
    pre = FILLER * ctx_copies
    msgs = [{"role": "user", "content": f"{pre}\n\nWrite exactly 120 words about the ocean."}]
    t0 = time.time()
    ttft = None
    out = 0
    with client.messages.stream(model=model, max_tokens=200, messages=msgs) as s:
        for ev in s:
            if ev.type == "content_block_delta" and ev.delta.type == "text_delta":
                if ttft is None:
                    ttft = time.time() - t0
        r = s.get_final_message()
    out = r.usage.output_tokens
    decode_t = max(0.05, (time.time() - t0) - (ttft or 0))
    return r.usage.input_tokens, out / decode_t


TOOLS = [
    {
        "name": "get_weather",
        "description": "Get weather for a city. Call when asked.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }
]


def tool_roundtrip(model: str) -> tuple[bool, float]:
    t0 = time.time()
    r = client.messages.create(
        model=model,
        max_tokens=300,
        tools=TOOLS,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
    )
    ok = any(b.type == "tool_use" and b.name == "get_weather" for b in r.content)
    return ok, time.time() - t0


def main() -> None:
    models = sys.argv[1:]
    if not models:
        print("usage: bench_models.py MODEL_A MODEL_B ...")
        sys.exit(1)
    results = {}
    for m in models:
        print(f"\n=== {m} ===")
        r = swap(m)
        if not r.get("ok"):
            print("  swap failed:", r)
            continue
        print(f"  loaded (dialect: {r.get('dialect')})")
        rows = []
        for copies in (0, 8, 32):
            inp, tps = decode_tps(m, copies)
            rows.append((inp, tps))
            print(f"  ctx ~{inp:>6} tok → {tps:5.1f} tok/s decode")
        ok, dt = tool_roundtrip(m)
        print(f"  tool round-trip: {'OK' if ok else 'MISS'} ({dt:.1f}s)")
        results[m] = rows
    print("\n--- summary (decode tok/s) ---")
    print(f"{'model':45} {'~1k':>7} {'~8k':>7} {'~32k':>7}")
    for m, rows in results.items():
        print(f"{m[:45]:45} " + " ".join(f"{tps:7.1f}" for _, tps in rows))


if __name__ == "__main__":
    main()
