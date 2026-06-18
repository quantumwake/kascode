"""Pure KV-cache reuse arithmetic, extracted from the MLX engine so it can be
unit-tested without a model.

Agent transcripts are append-only, so consecutive requests on the same thread
share a long prefix. We reuse the cached prefix and only process the divergent
tail. The cache itself lives in the engine (it's GPU state); these functions
just decide how much of it is still valid.
"""


def longest_common_prefix(cached: list[int], full: list[int]) -> int:
    """Length of the shared prefix of `cached` and `full`, capped so at least
    one token of `full` is always left to feed through generation (mlx_lm
    requires a non-empty prompt even on a 100%-cached continuation)."""
    if not full:
        return 0
    limit = min(len(cached), len(full) - 1)
    common = 0
    while common < limit and cached[common] == full[common]:
        common += 1
    return common
