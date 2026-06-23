"""/self-skill — self-learned skills v0 (see docs/enhancements/skills.md).

Reviews past sessions for recurring task patterns + capability gaps and asks the
model to PROPOSE skills that would automate them, writing the proposals to
<workdir>/.agent/skills/PROPOSALS-<ts>.md for review.

This is the propose-only first cut: it surfaces *what to build*. Actually running
self-authored skills arrives with the tool dispatcher/registry (a later
milestone) — until then `/self-skill` is the "observe → find gaps" loop and you
approve/build the proposals.
"""

import json
import pathlib
import time

from .prompts import SYSTEM

SELF_SKILL_PROMPT = (
    "You are improving YOURSELF as a local coding agent. Below is a history of "
    "past sessions in this workspace (task titles + handoff summaries). Study it "
    "for: recurring tasks, repeated multi-step tool sequences, and capability "
    "gaps where a reusable skill would have saved many steps.\n\n"
    "Propose 3–7 SKILLS to build. For each, give:\n"
    "  - name: kebab-case\n"
    "  - when-to-use: the trigger / situation\n"
    "  - what-it-does: the outcome\n"
    "  - sketch: concrete steps or commands it would run\n"
    "Also flag any existing skill that should be updated. Be specific to the work "
    "actually seen — no generic advice. Output clean markdown. Do NOT call tools."
)


def _gather_history(workdir, limit: int = 25, cap: int = 9000) -> str:
    """Recent session task titles + compaction summaries, newest first, capped."""
    sess = pathlib.Path(workdir) / ".agent" / "sessions"
    if not sess.exists():
        return ""
    parts: list[str] = []
    for d in sorted((p for p in sess.glob("*/") if p.is_dir()), reverse=True)[:limit]:
        tp = d / "transcript.json"
        if tp.exists():
            try:
                data = json.loads(tp.read_text())
                if data.get("title"):
                    parts.append(f"- {d.name}: {data['title']}")
            except (OSError, json.JSONDecodeError):
                pass
        for cf in sorted(d.glob("compaction-*.json")):
            try:
                summ = (json.loads(cf.read_text()).get("summary") or "").strip()
            except (OSError, json.JSONDecodeError):
                continue
            if summ:
                parts.append(f"    · {summ[:600]}")
    return "\n".join(parts)[:cap]


def self_skill(client, io, model: str, workdir, max_tokens: int = 8192) -> pathlib.Path | None:
    """Run the meta-analysis and write a proposals file. Returns its path (or None)."""
    history = _gather_history(workdir)
    if not history.strip():
        io.notice("[self-skill: no session history yet — nothing to learn from]")
        return None
    io.notice("[self-skill: reviewing past sessions for recurring patterns + skill gaps…]")
    req = [
        {"role": "user", "content": f"{SELF_SKILL_PROMPT}\n\n=== SESSION HISTORY ===\n{history}"}
    ]
    io.stream_started()
    response = None
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            messages=req,
        ) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if event.delta.type == "thinking_delta":
                    io.delta("thinking", event.delta.thinking)
                elif event.delta.type == "text_delta":
                    io.delta("text", event.delta.text)
            response = stream.get_final_message()
    finally:
        io.stream_finished(response.usage if response else None)
    proposals = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not proposals:
        io.notice("[self-skill: model returned no proposals]")
        return None
    d = pathlib.Path(workdir) / ".agent" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"PROPOSALS-{time.strftime('%Y%m%d-%H%M%S')}.md"
    out.write_text(f"# /self-skill proposals — {time.strftime('%Y-%m-%d %H:%M')}\n\n{proposals}\n")
    io.notice(f"[self-skill: proposals written → {out} — review, then we build the ones you want]")
    return out
