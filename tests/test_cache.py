"""Tests for the pure KV-cache reuse arithmetic extracted from the engine.

Run:  uv run python tests/test_cache.py
"""

import sys

sys.path.insert(0, ".")

from server.core.cache import longest_common_prefix as lcp

# Identical streams: cap one token short so generation always has input to feed.
assert lcp([1, 2, 3], [1, 2, 3]) == 2, lcp([1, 2, 3], [1, 2, 3])

# Pure append (continuation): cached is a strict prefix of full -> reuse all of it.
assert lcp([1, 2, 3], [1, 2, 3, 4, 5]) == 3

# Divergence at index 2 -> common prefix is 2.
assert lcp([1, 2, 9, 9], [1, 2, 3, 4, 5]) == 2

# Cached longer than full (full re-render shorter) -> capped at len(full)-1.
assert lcp([1, 2, 3, 4, 5], [1, 2, 3]) == 2

# Empty full -> nothing to reuse (and avoids feeding an empty prompt).
assert lcp([1, 2, 3], []) == 0

# Empty cache -> nothing reused.
assert lcp([], [1, 2, 3]) == 0

# Single-token full -> always 0 (must feed >= 1 token even if it matches).
assert lcp([1], [1]) == 0

print("all cache tests passed")
