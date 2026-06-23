"""Context compaction: the decode-speed relief valve.

Long sessions decode slower (full-attention layers read the whole KV cache per
token) and most of the transcript is file content already on disk. Compaction
replaces the transcript with a model-written handoff summary. _should_compact
decides WHEN (by reason); compact_messages does it, reusing the thread's KV
cache so the summary request is a near-instant cache hit, not a re-prefill.
"""

import anthropic

from .. import config
from .prompts import COMPACT_PROMPT, SUBAGENT_HINT, SYSTEM
from .toolspec import SUBAGENT_TOOL, TOOLS

# Fraction of the model's native window past which we MUST compact, even in the
# middle of a tool-calling sequence — sailing past the trained positions yields
# garbage. This is the hard ceiling; everything else is deferrable.
HARD_LIMIT_FRAC = 0.85


def classify_compaction(runner, input_tokens: int, compact_at: int):
    """Classify the compaction need as ("hard" | "soft" | "none", reason).

    - "hard": context-overflow — must compact NOW, even mid-tool-call (overrides
      the cooldown). Crash/garbage prevention.
    - "soft": decode-rate or absolute-size — an optimization, safe to DEFER to a
      turn boundary so we never interrupt a multi-step write. Respects cooldown.
    - "none": leave it.
    """
    frac = getattr(runner, "hard_limit_frac", HARD_LIMIT_FRAC)
    if runner.context_limit and input_tokens > int(frac * runner.context_limit):
        return "hard", f"hard context limit ({input_tokens}/{runner.context_limit})"
    if runner.compact_cooldown > 0:
        return "none", ""
    w = runner.tps_window
    if config.COMPACT_TPS and getattr(runner, "tps_valve", True) and len(w) >= 2:
        smoothed = sum(w) / len(w)
        if smoothed < config.COMPACT_TPS:
            return "soft", f"decode slowed to {smoothed:.1f} tok/s"
    if compact_at and (input_tokens - runner.compact_floor) > compact_at:
        return "soft", f"size {input_tokens} tok"
    return "none", ""


def should_compact(runner, input_tokens: int, compact_at: int):
    """Back-compat boolean wrapper around classify_compaction: (do, reason)."""
    level, reason = classify_compaction(runner, input_tokens, compact_at)
    return level != "none", reason


def run_compaction(
    client,
    messages,
    io,
    model,
    runner,
    input_tokens,
    reason,
    *,
    store=None,
    thread="main",
    max_tokens=16384,
    tools=None,
) -> None:
    """Compact `messages` in place and reset the post-compaction bookkeeping
    (floor / cooldown / decode-rate window)."""
    io.notice(f"[compaction trigger: {reason}]")
    compact_messages(
        client,
        messages,
        io,
        model,
        input_tokens,
        store=store,
        thread=thread,
        max_tokens=max_tokens,
        tools=tools,
    )
    summary_chars = len(messages[0]["content"]) if messages else 0
    runner.compact_floor = summary_chars // 4 + 1000  # ~tokens + system/tools
    runner.compact_cooldown = config.COMPACT_COOLDOWN
    runner.tps_window.clear()  # post-compaction decode is fast; don't re-trigger on stale lows


def _fmt_k(n: int | None) -> str:
    return f"{n / 1000:.0f}k" if n else ("0" if n == 0 else "?")


def ctx_command(runner, arg: str) -> str:
    """Handle `/ctx [<tokens>|max|auto|valve on|valve off]`: show or set the
    compaction policy live. Returns a status line. The hard limit is never
    exceeded — a numeric target is clamped to it."""
    native = runner.context_limit
    a = (arg or "").strip().lower()
    if a in ("max", "full"):
        runner.compact_at = 0  # disable the soft size cap
        runner.tps_valve = False  # disable the decode-speed valve -> ride to the hard limit
    elif a in ("auto", "default", "reset"):
        runner.compact_at = config.COMPACT_AT
        runner.tps_valve = True
    elif a in ("valve on", "on"):
        runner.tps_valve = True
    elif a in ("valve off", "off"):
        runner.tps_valve = False
    elif a:
        try:
            val = int(float(a[:-1]) * 1000) if a.endswith("k") else int(float(a))
        except ValueError:
            return f"usage: /ctx [<tokens>|max|auto|valve on|valve off] (got {arg.strip()!r})"
        if native:
            val = min(val, int(runner.hard_limit_frac * native))  # never exceed the hard limit
        runner.compact_at = max(0, val)
    used = getattr(runner, "last_input_tokens", 0)
    hard = int(runner.hard_limit_frac * native) if native else None
    pct = f" ({used * 100 // native}%)" if native and used else ""
    soft = "off" if not runner.compact_at else _fmt_k(runner.compact_at)
    return (
        f"context: window {_fmt_k(native) if native else 'unknown'} · "
        f"using ~{_fmt_k(used)}{pct} · hard limit {_fmt_k(hard) if hard else 'n/a'} · "
        f"soft-compact at {soft} · decode-valve {'on' if runner.tps_valve else 'off'}"
    )


def compact_messages(
    client: anthropic.Anthropic,
    messages: list,
    io,
    model: str,
    tokens_now: int | None = None,
    store=None,
    thread: str = "main",
    max_tokens: int = 16384,
    tools: list | None = None,
) -> None:
    """Replace the transcript with a model-written handoff summary.

    The summary request reuses the thread's existing KV cache: it sends the
    SAME system + tools as normal turns (so the continuation memo key matches)
    and merges the compaction prompt into the trailing user turn (so the
    request stays the +2-message shape continuation requires). That makes it a
    near-instant cache hit instead of a full re-prefill of the transcript.
    """
    io.notice(
        f"[compacting{f' {tokens_now} tokens' if tokens_now else ''} — "
        "summarizing, then context resets and decode speeds back up…]"
    )

    # Merge the compaction prompt into the last user turn (keeps continuation
    # shape); fall back to a new user message only if the last turn isn't user.
    req_messages = list(messages)
    if req_messages and req_messages[-1].get("role") == "user":
        content = req_messages[-1]["content"]
        blocks = list(content) if isinstance(content, list) else [{"type": "text", "text": content}]
        req_messages[-1] = {
            "role": "user",
            "content": blocks + [{"type": "text", "text": COMPACT_PROMPT}],
        }
    else:
        req_messages = req_messages + [{"role": "user", "content": COMPACT_PROMPT}]

    io.stream_started()
    response = None
    announced = False
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,  # room for thinking AND the summary, or it cuts off mid-thought
            system=f"{SYSTEM}\n\n{SUBAGENT_HINT}",  # must match normal turns for the cache key
            tools=tools if tools is not None else TOOLS + [SUBAGENT_TOOL],
            thinking={"type": "adaptive"},
            messages=req_messages,
            extra_headers=(
                {"x-agent-thread": thread, "x-agent-session-dir": str(store.dir)}
                if store is not None and getattr(store, "dir", None) is not None
                else {"x-agent-thread": thread}
            ),
        ) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if not announced:
                    io.notice("[step 2/2: writing the handoff summary…]")
                    announced = True
                # render the whole summary (and its reasoning) dimmed
                if event.delta.type == "thinking_delta":
                    io.delta("thinking", event.delta.thinking)
                elif event.delta.type == "text_delta":
                    io.delta("thinking", event.delta.text)
            response = stream.get_final_message()
    finally:
        io.stream_finished(response.usage if response else None)
    summary = "\n".join(b.text for b in response.content if b.type == "text")
    if store is not None:
        path = store.save_compaction(
            messages,
            summary,
            {"model": model, "input_tokens_at_compaction": tokens_now},
        )
        io.notice(f"[original context archived: {path}]")
    messages[:] = [
        {
            "role": "user",
            "content": (
                "[The session context was compacted. Handoff summary of everything "
                f"so far:]\n\n{summary}\n\n[Continue the task from where the summary "
                "leaves off. Files mentioned above are on disk — do NOT re-read whole "
                "files; read only the specific line ranges you need (read_file with "
                "start_line/end_line), and patch with edit_file.]"
            ),
        }
    ]
    io.notice(
        f"[context compacted{f': {tokens_now} tokens → summary' if tokens_now else ''} — "
        "the next turn re-reads only the summary, then stays fast]"
    )


# Back-compat aliases.
_should_compact = should_compact
