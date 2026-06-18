"""Anthropic-messages <-> native-dialect translation, dialects, and the
incremental output parser.

This package was split out of a single module; the public names are re-exported
here so existing imports (`from server.prompting import StreamParser`) keep
working unchanged.
"""

from .dialects import GemmaDialect, QwenDialect, _coerce, detect_dialect
from .gemma_args import _parse_value, parse_tool_call_body, render_tool_response
from .parser import StreamParser, _safe_len
from .translate import (
    _system_text,
    _tool_result_text,
    build_system,
    to_chat_messages,
    tools_payload,
)
from .wire import (
    CH_CLOSE,
    CH_OPEN,
    QUOTE,
    TC_CLOSE,
    TC_OPEN,
    Event,
    Schemas,
    new_tool_use_id,
)

__all__ = [
    "GemmaDialect",
    "QwenDialect",
    "detect_dialect",
    "parse_tool_call_body",
    "render_tool_response",
    "StreamParser",
    "_safe_len",
    "_parse_value",
    "_coerce",
    "_system_text",
    "_tool_result_text",
    "build_system",
    "to_chat_messages",
    "tools_payload",
    "CH_OPEN",
    "CH_CLOSE",
    "TC_OPEN",
    "TC_CLOSE",
    "QUOTE",
    "Event",
    "Schemas",
    "new_tool_use_id",
]
