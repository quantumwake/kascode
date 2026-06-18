"""Transcript helpers: message-shape utilities shared by the loop and the
session store. Pure, no I/O."""


def turn_label(messages: list) -> str:
    """Latest user text (task or steer), for checkpoint commit messages."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg["content"]
        if isinstance(content, str):
            return content[:60]
        for b in reversed(content):
            text = b.get("text") if isinstance(b, dict) else None
            if text:
                return text[:60]
    return "agent changes"


def jsonable(obj):
    """Recursively convert SDK content blocks to plain JSON-able structures."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [jsonable(x) for x in obj]
    return obj


# Back-compat aliases (these were private module names in the old monolith).
_turn_label = turn_label
_jsonable = jsonable
