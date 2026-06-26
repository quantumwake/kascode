"""Back-compat facade for the agent package.

The 1600-line monolith that used to live here was split into a hexagonal
layout (see docs/architecture/REFACTOR-hexagonal.md):

    agent/cli.py            composition root (main, serve_main)
    agent/config.py         config + server probes
    agent/core/             domain: loop, compaction, prompts, toolspec, …
    agent/ports/            Protocols (AgentIO, ToolExecutor)
    agent/adapters/         ConsoleIO/TUI, ToolRunner + tools, RAG, git, storage

This module re-exports the public names so existing imports keep working —
notably the TUI (`from agent import main as core`) and `agent.main:main`.
New code should import from the specific modules above.
"""

from .adapters.storage.filesystem import SessionStore
from .adapters.tools.bash import BashSession
from .adapters.tools.executor import ToolRunner
from .adapters.tools.files import PathResolver, SandboxViolation
from .adapters.ui.console import ConsoleIO, Heartbeat
from .cli import main, serve_main
from .config import (
    BASE_URL,
    COMPACT_AT,
    COMPACT_COOLDOWN,
    COMPACT_TPS,
    COMPACT_TPS_FRAC,
    MAX_TOKENS,
    MAX_TOOL_OUTPUT,
    MODEL,
    served_info,
    served_model,
)
from .core.ai_wellbeing import assess_wellbeing
from .core.compaction import compact_messages, should_compact
from .core.loop import agent_turn, run_subagent
from .core.prompts import COMPACT_PROMPT, SUBAGENT_HINT, SYSTEM, TRUNCATION_NOTE
from .core.self_skill import self_skill
from .core.subagent import SubagentIO
from .core.toolspec import RAG_TOOLS, SUBAGENT_MAX_ROUNDS, SUBAGENT_TOOL, TOOLS, WEB_TOOLS
from .core.transcript import jsonable, turn_label

# Legacy private aliases some callers/tests referenced.
_should_compact = should_compact
_turn_label = turn_label
_jsonable = jsonable

__all__ = [
    "main",
    "serve_main",
    "agent_turn",
    "run_subagent",
    "self_skill",
    "assess_wellbeing",
    "compact_messages",
    "should_compact",
    "ToolRunner",
    "SessionStore",
    "ConsoleIO",
    "Heartbeat",
    "SubagentIO",
    "BashSession",
    "PathResolver",
    "SandboxViolation",
    "TOOLS",
    "WEB_TOOLS",
    "RAG_TOOLS",
    "SUBAGENT_TOOL",
    "SUBAGENT_MAX_ROUNDS",
    "SYSTEM",
    "SUBAGENT_HINT",
    "COMPACT_PROMPT",
    "TRUNCATION_NOTE",
    "served_info",
    "served_model",
    "BASE_URL",
    "MODEL",
    "MAX_TOKENS",
    "COMPACT_AT",
    "COMPACT_COOLDOWN",
    "COMPACT_TPS",
    "COMPACT_TPS_FRAC",
    "MAX_TOOL_OUTPUT",
]


if __name__ == "__main__":
    main()
