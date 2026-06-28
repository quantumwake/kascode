"""Best-effort tool-call RECOVERY — a fallback chain for when the served model
emits a tool call in a format the active dialect doesn't parse.

Distilled models are unreliable here: e.g. Qwen3.6, told to use Qwen's
<tool_call><function=name> form, instead emits Claude's <function_calls><invoke>
XML or a bare JSON {"name":…,"arguments":…} — so the dialect parser misses it and
it leaks as text. When the turn ends with NO parsed tool call, the pipeline runs
this over the assembled text and tries each known format in turn. Returns a
{id, name, input} tool_use, or None if nothing tool-shaped is found.
"""

import json
import logging
import re
from typing import Any

from .wire import Schemas, new_tool_use_id

log = logging.getLogger("kas")

# Structured formats tried in order. Name-bearing markers, so low false-positive
# risk. (deepseek/kimi/harmony aren't here: their markers are distinctive enough
# that detect_dialect keys on them, so they don't leak past the primary parser.)
_PARSERS = (
    ("qwen-xml", lambda t, _v: _qwen_xml(t)),
    ("claude-xml", lambda t, _v: _claude_xml(t)),
    ("mistral-array", lambda t, _v: _mistral_array(t)),
    ("json", lambda t, _v: _json_object(t)),
    # python-call LAST and only with a known tool set — it would otherwise match
    # ordinary code like open(...)/range(...). Gated on the real tool names.
    # (lambda-wrapped like the rest so the tuple doesn't reference it before its
    # def below.)
    ("python-call", lambda t, v: _python_call(t, v)),
)


def recover_tool_call(
    text: str, schemas: Schemas | None = None, dialect_name: str | None = None
) -> dict | None:
    """Fallback ladder: try every known tool-call format on `text` until one
    yields a call whose name is a real tool, then return a {id, name, input}
    tool_use (or None). Logs a WARN when recovery is needed — that means the
    PRIMARY dialect parser missed, which is worth surfacing without crashing.

    `dialect_name` is only for the log line; `schemas` (tool name -> param types)
    both coerces argument types AND restricts which names count as tool calls."""
    if not text or not any(ch in text for ch in "<{[("):
        return None
    valid = set(schemas) if schemas else None
    for fmt, parse in _PARSERS:
        if fmt == "python-call" and not valid:
            continue  # too risky without a tool set to anchor on
        got = parse(text, valid)
        if not got or not got[0]:
            continue
        name, args = got
        if valid is not None and name not in valid:
            continue  # a call-shaped thing, but not one of OUR tools
        args = {k: _coerce(v, (schemas or {}).get(name, {}).get(k)) for k, v in args.items()}
        log.warning(
            "tool-call recovery: %sparser emitted no call; recovered %r via %s format "
            "(model isn't producing the active dialect's format)",
            f"'{dialect_name}' " if dialect_name else "",
            name,
            fmt,
        )
        return {"id": new_tool_use_id(), "name": name, "input": args}
    return None


def _python_call(text: str, valid: set[str] | None):
    """A Python-style call the model wrote as prose/code: NAME(k="v", k2=3). Only
    matches a NAME that is a known tool, so real code (open/range/print) is safe."""
    if not valid:
        return None
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", text):
        name = m.group(1)
        if name not in valid:
            continue
        args = _balanced_kwargs(text, m.end() - 1)
        if args is not None:
            return name, args
    return None


def _balanced_kwargs(text: str, open_idx: int) -> dict | None:
    """Parse `(k="v", k2=3, …)` starting at the '(' index, string-/paren-aware.
    Returns the kwargs dict, or None if the parens don't close."""
    depth, in_str, esc, quote, end = 0, False, False, "", -1
    for j in range(open_idx, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
        elif c in "\"'":
            in_str, quote = True, c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = j
                break
    if end == -1:
        return None
    body = text[open_idx + 1 : end]
    args: dict[str, Any] = {}
    for am in re.finditer(r"""(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^,()]+)""", body):
        k, v = am.group(1), am.group(2).strip()
        if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
            if v[0] == '"':
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    v = v[1:-1]
            else:
                v = v[1:-1]
        args[k] = v
    return args


def _qwen_xml(text: str):
    """<tool_call><function=NAME><parameter=k>v</parameter>…"""
    m = re.search(r"<function=([^>\n]+)>", text)
    if not m:
        return None
    args = {
        pm.group(1).strip(): pm.group(2)
        for pm in re.finditer(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", text, re.S)
    }
    return m.group(1).strip(), args


def _claude_xml(text: str):
    """<function_calls><invoke><tool_name>NAME</tool_name><arguments><k>v</k>…"""
    m = re.search(r"<tool_name>\s*(.*?)\s*</tool_name>", text, re.S) or re.search(
        r"<invoke\s+name=[\"']([^\"']+)[\"']", text
    )
    if not m:
        return None
    am = re.search(r"<arguments>(.*?)</arguments>", text, re.S)
    body = am.group(1) if am else text
    args = {
        pm.group(1): pm.group(2).strip()
        for pm in re.finditer(r"<([a-zA-Z_][\w.\-]*)>\n?(.*?)\n?</\1>", body, re.S)
        if pm.group(1) not in ("arguments", "invoke", "tool_name", "function_calls")
    }
    return m.group(1).strip(), args


def _mistral_array(text: str):
    """[TOOL_CALLS][{"name":…,"arguments":…}]"""
    m = re.search(r"\[TOOL_CALLS\]\s*(\[.*\])", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        c = data[0]
        return c.get("name"), c.get("arguments") or c.get("parameters") or {}
    return None


def _json_object(text: str):
    """A bare JSON tool call: {"name"|"tool_name"|"tool_id": …, "arguments"|"parameters": {…}}."""
    for obj in _json_objects(text):
        name = obj.get("name") or obj.get("tool_name") or obj.get("tool_id") or obj.get("function")
        args = obj.get("arguments")
        if args is None:
            args = obj.get("parameters")
        if args is None:
            args = obj.get("input", {})
        if name and isinstance(args, dict):
            return name, args
    return None


def _json_objects(text: str):
    """Yield each top-level {...} parsed as JSON (brace-matched, string-aware)."""
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, n):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        yield json.loads(text[i : j + 1])
                    except json.JSONDecodeError:
                        pass
                    i = j + 1
                    break
        else:
            return


def _coerce(value: Any, schema_type: str | None) -> Any:
    if not isinstance(value, str):
        return value
    try:
        if schema_type == "integer":
            return int(value.strip())
        if schema_type == "number":
            return float(value.strip())
        if schema_type == "boolean":
            return value.strip().lower() in ("true", "1", "yes")
        if schema_type in ("array", "object"):
            return json.loads(value)
    except (ValueError, json.JSONDecodeError):
        pass
    return value
