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


def should_compact(runner, input_tokens: int, compact_at: int):
    """Decide whether to compact, by reason. Returns (do, reason).

    Priority: (1) context-overflow safety — must compact, overrides cooldown;
    (2) decode-rate — the real symptom compaction relieves; (3) optional
    absolute token cap. (2) and (3) respect the cooldown.
    """
    if runner.context_limit and input_tokens > int(0.85 * runner.context_limit):
        return True, f"nearing context limit ({input_tokens}/{runner.context_limit})"
    if runner.compact_cooldown > 0:
        return False, ""
    w = runner.tps_window
    if config.COMPACT_TPS and len(w) >= 2:
        smoothed = sum(w) / len(w)
        if smoothed < config.COMPACT_TPS:
            return True, f"decode slowed to {smoothed:.1f} tok/s"
    if compact_at and (input_tokens - runner.compact_floor) > compact_at:
        return True, f"size {input_tokens} tok"
    return False, ""


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
        req_messages[-1] = {"role": "user", "content": blocks + [{"type": "text", "text": COMPACT_PROMPT}]}
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
            extra_headers={"x-agent-thread": thread},
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
