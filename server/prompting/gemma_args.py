"""Gemma tool-call argument syntax <-> python objects.

Gemma serializes call arguments as: strings are <|"|>-quoted, numbers and
booleans bare, dicts/lists like JSON without quoted keys at the call level.
"""

from typing import Any

from .wire import QUOTE, new_tool_use_id


def _parse_value(s: str, i: int) -> tuple[Any, int]:
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    if s.startswith(QUOTE, i):
        j = s.find(QUOTE, i + len(QUOTE))
        if j == -1:
            raise ValueError("unterminated string")
        return s[i + len(QUOTE) : j], j + len(QUOTE)
    if i < len(s) and s[i] == "{":
        obj: dict[str, Any] = {}
        i += 1
        while True:
            while i < len(s) and s[i] in " \t\n\r,":
                i += 1
            if i >= len(s):
                raise ValueError("unterminated object")
            if s[i] == "}":
                return obj, i + 1
            # Read the key: quoted (string syntax) or bare (up to the ':').
            if s.startswith(QUOTE, i):
                j = s.find(QUOTE, i + len(QUOTE))
                key = s[i + len(QUOTE) : j]
                i = j + len(QUOTE)
            else:
                j = s.index(":", i)
                key = s[i:j].strip()
                i = j  # leave i ON the ':' so the next line handles both branches
            # Skip the key:value ':'. For a quoted key that's the next colon;
            # for a bare key i is already on it, so this re-locates the same one.
            i = s.index(":", i) + 1
            val, i = _parse_value(s, i)
            obj[key] = val
    if i < len(s) and s[i] == "[":
        arr: list[Any] = []
        i += 1
        while True:
            while i < len(s) and s[i] in " \t\n\r,":
                i += 1
            if i >= len(s):
                raise ValueError("unterminated array")
            if s[i] == "]":
                return arr, i + 1
            val, i = _parse_value(s, i)
            arr.append(val)
    j = i
    while j < len(s) and s[j] not in ",}]":
        j += 1
    tok = s[i:j].strip()
    if tok == "true":
        return True, j
    if tok == "false":
        return False, j
    if tok in ("null", "None"):
        return None, j
    try:
        return int(tok), j
    except ValueError:
        pass
    try:
        return float(tok), j
    except ValueError:
        return tok, j


def render_tool_response(name: str, content: str) -> str:
    """Byte-exact equivalent of the chat template's format_tool_response_block
    for string content — used to append tool results directly to the raw
    cached token stream (continuation path) without re-rendering history."""
    return f"<|tool_response>response:{name}{{value:{QUOTE}{content}{QUOTE}}}<tool_response|>"


def parse_tool_call_body(body: str) -> dict[str, Any]:
    """'call:get_weather{city:<|"|>Paris<|"|>}' -> tool_use dict."""
    body = body.strip()
    if body.startswith("call:"):
        body = body[len("call:") :]
    brace = body.find("{")
    if brace == -1:
        name, args = body.strip(), {}
    else:
        name = body[:brace].strip()
        args, _ = _parse_value(body, brace)
        if not isinstance(args, dict):
            raise ValueError("tool call arguments must be an object")
    if not name:
        raise ValueError("empty tool name")
    return {"id": new_tool_use_id(), "name": name, "input": args}
