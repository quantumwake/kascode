"""Summarize per-request performance from server.log.  Run: make perf"""

import re
import sys

LINE = re.compile(
    r"(?P<time>\d\d:\d\d:\d\d).* in=(?P<inp>\d+) tok \(cache hit (?P<hit>\d+), "
    r"prefilled (?P<pre>\d+) @ (?P<ptps>\d+) tok/s\) \| out=(?P<out>\d+) tok @ "
    r"(?P<gtps>[\d.]+) tok/s \| peak (?P<peak>[\d.]+) GB"
)


def main(path: str = "server.log", last: int = 20) -> None:
    rows, continuations, quantized = [], 0, 0
    for line in open(path):
        if "continuation:" in line:
            continuations += 1
        if "quantized" in line and "KV caches" in line:
            quantized += 1
        m = LINE.search(line)
        if m:
            rows.append(
                {
                    k: float(v) if "." in v else (v if k == "time" else int(v))
                    for k, v in m.groupdict().items()
                }
            )
    if not rows:
        print("no request lines found in", path)
        return

    recent = rows[-last:]
    print(
        f"{'time':8} {'in':>7} {'cache%':>7} {'prefill':>8} "
        f"{'pf tok/s':>9} {'out':>6} {'gen tok/s':>10}"
    )
    for r in recent:
        pct = 100 * r["hit"] / r["inp"] if r["inp"] else 0
        print(
            f"{r['time']:8} {r['inp']:>7} {pct:>6.0f}% {r['pre']:>8} "
            f"{r['ptps']:>9} {r['out']:>6} {r['gtps']:>10.1f}"
        )

    n = len(rows)
    hits = sum(r["hit"] for r in rows)
    inp = sum(r["inp"] for r in rows)
    print(
        f"\n{n} requests · lifetime cache hit {100 * hits / inp:.0f}% · "
        f"{continuations} continuation turns · {quantized} KV-quantization events"
    )

    # generation speed by context size bucket — the long-context decode story
    buckets = [(0, 4000), (4000, 12000), (12000, 24000), (24000, 10**9)]
    print("\ngen tok/s by context size:")
    for lo, hi in buckets:
        sample = [r["gtps"] for r in rows if lo <= r["inp"] < hi and r["out"] >= 20]
        if sample:
            label = f"{lo // 1000}k-{hi // 1000}k" if hi < 10**9 else f">{lo // 1000}k"
            print(f"  {label:>9}: {sum(sample) / len(sample):5.1f} tok/s  (n={len(sample)})")


if __name__ == "__main__":
    main(*sys.argv[1:])
