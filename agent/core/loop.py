"""The agentic loop: one user turn = stream the response, execute any tool_use
blocks, feed tool_result blocks back, repeat until the model stops calling
tools. Also hosts subagent delegation (it and agent_turn are mutually
recursive). Depends only on ports (the io and the runner), prompts, toolspecs,
and the compaction/transcript helpers — never on a concrete UI or engine.
"""

import time

import anthropic
import httpx

from .. import config
from ..config import _truncate
from .compaction import classify_compaction, run_compaction
from .prompts import ROUND_WRAPUP_NOTE, SUBAGENT_HINT, SYSTEM, TRUNCATION_NOTE
from .subagent import SubagentIO
from .toolspec import (
    IMAGE_TOOLS,
    RAG_TOOLS,
    SUBAGENT_MAX_ROUNDS,
    SUBAGENT_ROUNDS_CAP,
    SUBAGENT_TOOL,
    TOOLS,
    WEB_TOOLS,
)
from .transcript import turn_label

_subagent_seq = 0


def run_subagent(
    client: anthropic.Anthropic,
    runner,
    io,
    model: str,
    max_tokens: int,
    args: dict,
) -> tuple[str, bool]:
    """Execute one subagent task in a fresh context; return its final report."""
    global _subagent_seq
    task = (args or {}).get("task", "").strip()
    if not task:
        return "subagent requires a non-empty 'task'", True
    if args.get("report"):
        task += f"\n\nYour final reply MUST contain: {args['report']}"
    _subagent_seq += 1
    n = _subagent_seq
    thread = f"sub-{n}"  # own KV-cache slot + memo, isolated from main
    # The parent picks the round budget by task complexity; clamp to the ceiling.
    requested = (args or {}).get("max_rounds")
    try:
        budget = (
            max(1, min(int(requested), SUBAGENT_ROUNDS_CAP)) if requested else SUBAGENT_MAX_ROUNDS
        )
    except (TypeError, ValueError):
        budget = SUBAGENT_MAX_ROUNDS
    label = task[:100].splitlines()[0]
    io.notice(f"[subagent[{n}] ▶ {label}… (≤{budget} rounds)]")
    sub_io = SubagentIO(io, label=label, n=n)
    if hasattr(io, "subagent_started"):
        io.subagent_started(sub_io)
    messages: list = [{"role": "user", "content": task}]
    try:
        agent_turn(
            client,
            messages,
            runner,
            sub_io,
            model=model,
            max_tokens=max_tokens,
            compact_at=0,  # bounded by rounds instead
            is_subagent=True,
            max_rounds=budget,
            thread=thread,
        )
    except Exception as exc:
        sub_io.status = "error"
        if hasattr(io, "subagent_finished"):
            io.subagent_finished(sub_io, False)
        return f"subagent failed: {type(exc).__name__}: {exc}", True
    final = ""
    if messages and messages[-1].get("role") == "assistant":
        content = messages[-1]["content"]
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        final = "\n\n".join(
            (b.text if hasattr(b, "text") else b.get("text", ""))
            for b in blocks
            if (getattr(b, "type", None) or b.get("type")) == "text"
        ).strip()
    sub_io.status = "done" if final else "empty"
    if final:
        sub_io.buffer.append(f"[report] {final}")
    io.notice(f"[subagent[{n}] ✔ done]")
    if hasattr(io, "subagent_finished"):
        io.subagent_finished(sub_io, bool(final))
    if not final:
        return "subagent finished without a final report", True
    return _truncate(final), False


def agent_turn(
    client: anthropic.Anthropic,
    messages: list,
    runner,
    io,
    model: str | None = None,
    max_tokens: int | None = None,
    compact_at: int | None = None,
    store=None,
    is_subagent: bool = False,
    max_rounds: int | None = None,
    thread: str = "main",
) -> None:
    """One user turn: loop until the model stops calling tools.

    Steering messages submitted mid-run (io.drain_steers) are injected as user
    text alongside the next tool results, so the model sees them at the next
    boundary without interrupting generation.
    """
    model = model or config.MODEL
    max_tokens = max_tokens or config.MAX_TOKENS
    # The soft size cap lives on the runner (so /ctx can change it live); a
    # subagent passes compact_at=0 to disable size-based compaction.
    compact_at = runner.compact_at if compact_at is None else compact_at
    if model is None:
        raise ValueError("no model resolved — is the server running?")
    tools = list(TOOLS)
    if not is_subagent:
        tools.append(SUBAGENT_TOOL)
    if runner.rag:
        tools += RAG_TOOLS  # opt-in; stable per session so the cache key holds
    if runner.net:
        tools += WEB_TOOLS
    if getattr(runner, "art", False):
        tools += IMAGE_TOOLS
    # Tell the server which session dir to persist/rehydrate this thread's KV
    # cache under (server only acts on it when KV persistence is enabled).
    headers = {"x-agent-thread": thread}
    if (
        store is not None
        and getattr(store, "dir", None) is not None
        and getattr(runner, "persist_kv", True)
    ):
        headers["x-agent-session-dir"] = str(store.dir)
    truncations = 0
    rounds = 0
    reconnects = 0  # consecutive dropped-connection retries for the current turn
    compact_pending = False  # a soft compaction is owed; flush it at a safe boundary
    while True:
        rounds += 1
        if max_rounds is not None and rounds > max_rounds:
            io.notice(f"[round limit {max_rounds} reached — wrapping up]")
            return
        io.clear_abort()
        io.stream_started()
        response = None
        aborted = False
        partial: list[dict] = []  # accumulated deltas, kept if interrupted
        try:
            # max_retries=0: own the retry here so a dropped connection is
            # surfaced (the SDK's built-in retry is silent).
            with client.with_options(max_retries=0).messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=SYSTEM if is_subagent else f"{SYSTEM}\n\n{SUBAGENT_HINT}",
                tools=tools,
                thinking={"type": "adaptive"},
                messages=messages,
                extra_headers=headers,
            ) as stream:
                for event in stream:
                    if io.should_abort():
                        aborted = True
                        break  # closing the stream cancels server-side generation
                    if event.type == "content_block_delta":
                        kind = field = None
                        if event.delta.type == "thinking_delta":
                            kind, field, piece = "thinking", "thinking", event.delta.thinking
                        elif event.delta.type == "text_delta":
                            kind, field, piece = "text", "text", event.delta.text
                        if kind is not None:
                            io.delta(kind, piece)
                            if partial and partial[-1]["type"] == kind:
                                partial[-1][field] += piece
                            else:
                                block = {"type": kind, field: piece}
                                if kind == "thinking":
                                    block["signature"] = ""
                                partial.append(block)
                if not aborted:
                    response = stream.get_final_message()
        except (
            anthropic.APITimeoutError,
            anthropic.APIConnectionError,
            # A read timeout (or server-side disconnect) raised mid-SSE-iteration
            # isn't always wrapped by the SDK — the raw httpx error escapes here.
            # Treat it the same as a dropped connection so it reconnects instead
            # of leaking to the TUI's generic error branch.
            httpx.TimeoutException,
            httpx.RemoteProtocolError,
        ) as exc:
            io.stream_finished(None)
            if partial or reconnects >= 3:
                raise  # content already shown, or out of retries — give up
            reconnects += 1
            io.notice(f"[connection dropped ({type(exc).__name__}) — reconnecting {reconnects}/3…]")
            rounds -= 1  # a reconnect isn't a real round
            time.sleep(min(2 * reconnects, 6))
            continue
        except BaseException:
            io.stream_finished(None)  # always stop the heartbeat
            raise
        else:
            reconnects = 0  # this turn's stream completed cleanly
            io.stream_finished(response.usage if response else None)

        if aborted:
            kept = [b for b in partial if (b.get("text") or b.get("thinking", "")).strip()]
            if kept:
                messages.append({"role": "assistant", "content": kept})
            # Pause: stop cleanly, keep partial, let the caller save + exit.
            # Resume re-enters the loop and continues the task.
            if io.should_pause():
                io.notice("[paused — partial output kept; resume to continue]")
                return
            io.notice("[response interrupted — partial output kept]")
            steers = [
                {"type": "text", "text": f"[user steering message] {s}"} for s in io.drain_steers()
            ]
            if steers:
                io.notice(f"[injecting {len(steers)} steering message(s)]")
                messages.append({"role": "user", "content": steers})
                continue
            return

        messages.append({"role": "assistant", "content": response.content})

        truncated = response.stop_reason == "max_tokens"
        if truncated:
            truncations += 1
            io.notice(
                f"[response hit the {max_tokens}-token output limit; recovery {truncations}/3]"
            )

        # Execute any COMPLETED tool calls (present even when a later call in
        # the same response was truncated).
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            io.tool_call(block.name, block.input)
            if block.name == "subagent":
                if is_subagent:
                    output, is_error = "subagents cannot spawn subagents", True
                else:
                    output, is_error = run_subagent(
                        client, runner, io, model, max_tokens, block.input
                    )
            else:
                output, is_error = runner.run(block.name, block.input)
            io.tool_result(output, is_error)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": is_error,
                }
            )

        if results:
            sha = runner.checkpoint(turn_label(messages))
            if sha:
                io.notice(f"[checkpoint {sha}]")

        steers = [
            {"type": "text", "text": f"[user steering message] {s}"} for s in io.drain_steers()
        ]
        if steers:
            io.notice(f"[injecting {len(steers)} steering message(s)]")

        if truncated and truncations >= 3:
            io.notice("[giving up after 3 truncated responses — try a smaller task]")
            if results or steers:
                messages.append({"role": "user", "content": results + steers})
            return
        if truncated:
            content: list = results + steers + [{"type": "text", "text": TRUNCATION_NOTE}]
            messages.append({"role": "user", "content": content})
            continue
        # Sample decode-rate + context size for the compaction policy and /ctx.
        runner.tps_window.append(io.last_decode_tps)
        runner.last_input_tokens = response.usage.input_tokens
        level, reason = classify_compaction(runner, response.usage.input_tokens, compact_at)

        if not results and not steers:
            # Turn boundary: the model stopped calling tools — the SAFE place to
            # compact. Flush a deferred soft compaction (or a fresh trigger) so
            # the next user turn starts small and fast.
            if compact_pending or level != "none":
                run_compaction(
                    client,
                    messages,
                    io,
                    model,
                    runner,
                    response.usage.input_tokens,
                    reason or "deferred to end of turn",
                    store=store,
                    thread=thread,
                    max_tokens=max_tokens,
                    tools=tools,
                )
            return

        content_back: list = results + steers
        # Soft landing for a round-budgeted run (subagents): a round before the
        # hard cap, tell the model to wrap up and report — so hitting the limit
        # yields a usable summary instead of getting cut off mid-tool-call.
        if max_rounds is not None and rounds >= max_rounds - 1:
            content_back = content_back + [
                {
                    "type": "text",
                    "text": ROUND_WRAPUP_NOTE.format(rounds=rounds, max_rounds=max_rounds),
                }
            ]
        messages.append({"role": "user", "content": content_back})

        # Mid-sequence: only the HARD context-overflow limit may compact here —
        # compacting in the middle of a multi-step operation (e.g. a chunked
        # write) loses the fine-grained in-progress state and corrupts it. Soft
        # triggers (decode-speed, size) DEFER to the next turn boundary above.
        if level == "hard":
            run_compaction(
                client,
                messages,
                io,
                model,
                runner,
                response.usage.input_tokens,
                reason,
                store=store,
                thread=thread,
                max_tokens=max_tokens,
                tools=tools,
            )
            compact_pending = False
        elif level == "soft":
            if not compact_pending:
                io.notice(f"[compaction deferred to a safe point: {reason}]")
            compact_pending = True
        elif runner.compact_cooldown > 0:
            runner.compact_cooldown -= 1
