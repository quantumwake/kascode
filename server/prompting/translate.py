"""Translate Anthropic-style request messages -> the model's native chat
dialect shapes consumed by `apply_chat_template`.

  - tools         -> [{"type": "function", "function": {...}}]      (tools= kwarg)
  - tool_use      -> assistant message {"tool_calls": [...]}
  - tool_result   -> {"role": "tool", "tool_call_id": ..., "content": ...}
  - thinking      -> enable_thinking=True / "reasoning" field on assistant turns
"""

from typing import Any

from ..schema import Message, TextBlock, ThinkingBlock, ToolDef, ToolResultBlock, ToolUseBlock
from .dialects import GemmaDialect


def _system_text(system: str | list[dict[str, Any]] | None) -> str:
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if b.get("type") == "text")


def build_system(
    system: str | list[dict[str, Any]] | None,
    tool_choice: dict[str, Any] | None,
) -> str:
    parts = []
    base = _system_text(system)
    if base:
        parts.append(base)
    choice_type = (tool_choice or {}).get("type")
    if choice_type == "any":
        parts.append("You MUST call one of the available tools in this response.")
    elif choice_type == "tool":
        parts.append(f"You MUST call the tool `{tool_choice['name']}` in this response.")
    return "\n\n".join(parts)


def tools_payload(tools: list[ToolDef]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _tool_result_text(block: ToolResultBlock) -> str:
    content = block.content
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
    text = content or ""
    if block.is_error:
        text = f"ERROR: {text}"
    return text


def to_chat_messages(
    messages: list[Message],
    system: str | list[dict[str, Any]] | None,
    tool_choice: dict[str, Any] | None,
    dialect=None,
) -> list[dict[str, Any]]:
    dialect = dialect or GemmaDialect()
    chat: list[dict[str, Any]] = []
    sys_text = build_system(system, tool_choice)
    if sys_text:
        chat.append({"role": "system", "content": sys_text})

    for msg in messages:
        if isinstance(msg.content, str):
            blocks: list[Any] = [TextBlock(text=msg.content)]
        else:
            blocks = list(msg.content)

        if msg.role == "assistant":
            texts, reasoning, tool_calls = [], [], []
            for b in blocks:
                if isinstance(b, TextBlock):
                    texts.append(b.text)
                elif isinstance(b, ThinkingBlock):
                    reasoning.append(b.thinking)
                elif isinstance(b, ToolUseBlock):
                    tool_calls.append(
                        {
                            "id": b.id,
                            "type": "function",
                            "function": {"name": b.name, "arguments": b.input},
                        }
                    )
            chat.append(dialect.assistant_entry(texts, reasoning, tool_calls))
        else:
            # Tool results become role:"tool" messages (the template forward-scans
            # them from the preceding assistant tool_calls turn); remaining text
            # becomes a normal user message.
            texts = []
            for b in blocks:
                if isinstance(b, ToolResultBlock):
                    chat.append(
                        {
                            "role": "tool",
                            "tool_call_id": b.tool_use_id,
                            "content": _tool_result_text(b),
                        }
                    )
                elif isinstance(b, TextBlock):
                    texts.append(b.text)
            if texts:
                text = "\n\n".join(texts)
                if chat and chat[-1]["role"] == "user":
                    chat[-1]["content"] += "\n\n" + text
                else:
                    chat.append({"role": "user", "content": text})
    return chat
