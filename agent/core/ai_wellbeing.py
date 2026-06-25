"""/ai-wellbeing — a reflective self-assessment of the agent's state.

Takes the current conversation context and asks the model to rate its OWN state
across a small wellbeing framework (cognitive load, stress, clarity, confidence,
frustration, engagement, autonomy, context pressure), each 0.0–1.0. The scores
are shown in the work view and appended to ~/.kascode/ai-wellbeing.csv
(append-only) alongside the workdir name, a task summary, the timestamp, and the
model — a longitudinal log of how demanding / clear / stressful the work has felt.

It's a meta check-in, not a task: the conversation is flattened into a single
prompt (so no tool_use/tool_result pairing to honour) and the agent's transcript
is never mutated.
"""

import csv
import json
import pathlib
import time

from .prompts import SYSTEM

# The wellbeing dimensions, in CSV-column order. For all but clarity/confidence/
# autonomy/engagement, higher = more of a burden; those four are "more is better".
DIMENSIONS = [
    "cognitive_load",
    "stress",
    "clarity",
    "confidence",
    "frustration",
    "engagement",
    "autonomy",
    "context_pressure",
]
CSV_PATH = pathlib.Path.home() / ".kascode" / "ai-wellbeing.csv"

AI_WELLBEING_PROMPT = (
    "Pause and honestly self-assess YOUR current state as the agent working this "
    "session. This is a reflective check-in, not a task. Considering the "
    "conversation so far, rate each dimension from 0.0 (none) to 1.0 (maximal):\n"
    "  - cognitive_load: how mentally demanding the current work is\n"
    "  - stress: pressure from conflicting constraints, ambiguity, or urgency\n"
    "  - clarity: how clear the goal and requirements are (1.0 = fully clear)\n"
    "  - confidence: confidence in the current approach (1.0 = high)\n"
    "  - frustration: from repeated failures, dead-ends, or churn\n"
    "  - engagement: interest / sense of flow (1.0 = fully engaged)\n"
    "  - autonomy: freedom to choose the approach (1.0 = full autonomy)\n"
    "  - context_pressure: strain from a long or near-full context window\n\n"
    "Give ONE honest sentence of reflection, then output ONLY a JSON object on the "
    'final line with those eight keys (floats 0.0–1.0) plus a short "note" string. '
    "Do NOT call tools."
)


def _flatten_context(messages: list, limit: int = 18, cap: int = 8000) -> str:
    """Render the most recent messages to plain text (no tool-pairing concerns),
    keeping the tail within `cap` chars."""
    parts: list[str] = []
    for m in messages[-limit:]:
        role = m.get("role")
        content = m.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for b in blocks:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and b.get("text"):
                parts.append(f"{role}: {b['text']}")
            elif t == "thinking" and b.get("thinking"):
                parts.append(f"{role} (thinking): {b['thinking']}")
            elif t == "tool_use":
                parts.append(f"{role}: [calls tool {b.get('name')}]")
            elif t == "tool_result":
                out = b.get("content", "")
                if isinstance(out, list):
                    out = "".join(x.get("text", "") for x in out if isinstance(x, dict))
                parts.append(f"tool_result: {str(out)[:200]}")
    return "\n".join(parts)[-cap:]  # keep the most recent context


def _task_summary(messages: list) -> str:
    """A one-line task summary from the first user message."""
    for m in messages:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c.replace("\n", " ")[:120]
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    return b["text"].replace("\n", " ")[:120]
    return ""


def parse_scores(text: str) -> dict | None:
    """Pull the trailing JSON score object out of the model's reply. Returns the
    clamped dimension scores (+ note), or None if no valid object/scores found."""
    i, j = text.rfind("{"), text.rfind("}")
    if i == -1 or j == -1 or j < i:
        return None
    try:
        obj = json.loads(text[i : j + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    out: dict = {}
    for d in DIMENSIONS:
        v = obj.get(d)
        if isinstance(v, int | float) and not isinstance(v, bool):
            out[d] = max(0.0, min(1.0, float(v)))  # clamp to [0, 1]
    if not out:
        return None
    out["note"] = str(obj.get("note", ""))[:200]
    return out


def append_csv(workdir, model: str, task: str, scores: dict, path: pathlib.Path = CSV_PATH) -> None:
    """Append one assessment row (header written if the file is new)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "workdir", "model", "task_summary", *DIMENSIONS, "note"])
        w.writerow(
            [
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                pathlib.Path(workdir).name,
                model,
                task,
                *[scores.get(d, "") for d in DIMENSIONS],
                scores.get("note", ""),
            ]
        )


def assess_wellbeing(
    client, io, messages: list, model: str, workdir, max_tokens: int = 4096
) -> None:
    """Run the reflective assessment, show the scores, and log them to the CSV."""
    if not messages:
        io.notice("[ai-wellbeing: no conversation yet — nothing to assess]")
        return
    io.notice("[ai-wellbeing: reflecting on the current session…]")
    context = _flatten_context(messages)
    req = [{"role": "user", "content": f"{AI_WELLBEING_PROMPT}\n\n=== CONVERSATION ===\n{context}"}]
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
    text = "".join(b.text for b in response.content if b.type == "text") if response else ""
    scores = parse_scores(text)
    if not scores:
        io.notice("[ai-wellbeing: couldn't parse a score from the response]")
        return
    line = "  ·  ".join(f"{d.replace('_', ' ')} {scores[d]:.2f}" for d in DIMENSIONS if d in scores)
    io.notice(f"[ai-wellbeing] {line}")
    if scores.get("note"):
        io.notice(f"[ai-wellbeing] note: {scores['note']}")
    try:
        append_csv(workdir, model, _task_summary(messages), scores, path=CSV_PATH)
        io.notice(f"[ai-wellbeing: logged → {CSV_PATH}]")
    except OSError as exc:
        io.notice(f"[ai-wellbeing: CSV log failed: {exc}]")
