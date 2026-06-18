"""Shared wire-format constants and small helpers used across the dialects,
the argument parser, and the stream parser. Kept dependency-free so every
other prompting module can import it without cycles.
"""

import uuid
from typing import Any

# Gemma channel / tool-call markers.
CH_OPEN = "<|channel>"
CH_CLOSE = "<channel|>"
TC_OPEN = "<|tool_call>"
TC_CLOSE = "<tool_call|>"
QUOTE = '<|"|>'

Event = tuple[str, Any]  # ("text", str) | ("thinking", str) | ("tool_use", dict)

# Schemas map for argument coercion: {tool_name: {param: json_schema_type}}
Schemas = dict[str, dict[str, str]]


def new_tool_use_id() -> str:
    return "toolu_" + uuid.uuid4().hex[:24]
