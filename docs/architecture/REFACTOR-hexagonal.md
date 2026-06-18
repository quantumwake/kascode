# Hexagonal refactor — spec & plan

Status: **in progress** (branch `refactor/hexagonal-architecture`)

## Goal

Restructure the four oversized modules into a clean **ports & adapters
(hexagonal)** layout, with a characterization-test safety net added *first* so
the refactor is provably behaviour-preserving. Two behavioural changes ride
along: an opt-in **filesystem sandbox** and a fix for the **quantized-cache
trim cliff**.

Oversized today:

| file | lines | becomes |
|---|---|---|
| `agent/main.py` | 1628 | `agent/{cli,config}.py` + `agent/core/*` + `agent/ports/*` + `agent/adapters/*` |
| `agent/tui.py` | 743 | `agent/adapters/ui/tui/*` |
| `server/app.py` | 562 | `server/app.py` (thin) + `server/core/*` + `server/adapters/http/*` |
| `server/prompting.py` | 511 | `server/prompting/{dialects,parser,translate,gemma_args}.py` |

## Architecture principles

- **The hexagon = domain logic; the edges = ports (Protocols); the outside =
  adapters.** Domain modules import only stdlib + ports, never frameworks
  (FastAPI, Textual, anthropic SDK, sqlite, git).
- **Composition roots** (`agent/cli.py`, `server/app.py`) are the only places
  that import concrete adapters and wire them to the domain.
- **Pythonic, not Java cosplay.** Ports are `typing.Protocol`; DI is
  constructor injection; cohesive modules over one-class-per-file.
- **Back-compat shims.** Each split module keeps its old import path working
  (`from server.prompting import StreamParser`) via re-exports, so tests and
  external callers don't break mid-refactor.

## Target layout

### `agent/` (the client / orchestrator)

```
agent/
  __main__.py            # python -m agent
  cli.py                 # composition root: argparse, wire adapters, dispatch
  config.py              # AgentConfig (env+args), tunable constants
  core/                  # DOMAIN — pure
    loop.py              # agent_turn: turn orchestration via ports
    compaction.py        # _should_compact policy + compaction orchestration
    prompts.py           # SYSTEM / SUBAGENT_HINT / COMPACT_PROMPT / TRUNCATION_NOTE
    toolspec.py          # TOOLS / WEB_TOOLS / RAG_TOOLS / SUBAGENT_TOOL (pure data)
    transcript.py        # _turn_label, _jsonable, steering helpers
  ports/                 # PROTOCOLS (hexagon edges)
    ui.py                # AgentIO
    llm.py               # LLMClient (anthropic-shaped streaming)
    tools.py             # ToolExecutor + ToolResult
    retrieval.py         # Retriever
    workspace.py         # Checkpointer
    storage.py           # SessionStore
  adapters/
    ui/console.py        # ConsoleIO
    ui/subagent.py       # SubagentIO
    ui/heartbeat.py      # Heartbeat
    ui/tui/              # Textual app, split
    tools/executor.py    # ToolRunner (implements ToolExecutor)
    tools/bash.py        # BashSession + bash* handlers + terminal cleaning
    tools/files.py       # read/write/edit/list + PathResolver (SANDBOX lives here)
    tools/web.py         # web_search / web_fetch
    tools/recall.py      # recall (uses Retriever)
    retrieval/bm25.py    # RagIndex (was agent/rag.py)
    workspace/git.py     # GitCheckpointer
    storage/filesystem.py# FileSessionStore + compaction archive
    subagent.py          # run_subagent
    daemon.py            # `kas serve` daemon management
```

### `server/` (the MLX inference server)

```
server/
  cli.py                 # kas-server entry (unchanged)
  app.py                 # composition root: FastAPI app, lifespan, handlers, routes (thin)
  config.py              # MODEL_ID, DEFAULT_MAX_TOKENS, env knobs
  core/
    ports.py             # InferenceEngine Protocol
    continuation.py      # ContinuationMemo: _try_continuation, _echo_matches, _req_key
    pipeline.py          # _run: engine chunks -> normalized API events (use case)
  adapters/
    mlx_engine.py        # Engine (was server/engine.py) — implements InferenceEngine
    http/routes.py       # /v1/messages, /v1/models[/select], /v1/stats
    http/sse.py          # _sse / _stream / _stream_safe
    http/complete.py     # _complete (non-streaming)
  prompting/
    dialects.py          # GemmaDialect, QwenDialect, detect_dialect
    parser.py            # StreamParser, _safe_len, Event
    translate.py         # to_chat_messages, build_system, tools_payload
    gemma_args.py        # _parse_value, parse_tool_call_body, render_tool_response
  schema.py              # pydantic (unchanged)
```

## Behavioural changes (riding along)

### 1. Filesystem sandbox (`--sandbox`)
`agent/adapters/tools/files.py::PathResolver`. When enabled, `read_file`,
`write_file`, `edit_file`, `list_dir` reject paths that resolve outside the
workdir (`Path.resolve().is_relative_to(workdir)`); absolute paths and `../`
escapes return a tool error instead of touching the host. Off by default
(preserves current behaviour); opt-in flag + `KAS_SANDBOX=1`.

### 2. Quantized-cache trim cliff (`server/adapters/mlx_engine.py`)
Today a thread that crosses `KAS_KV_START` gets its full-attention KV layers
quantized; the next turn needing a trim can't trim a quantized cache, so it
falls into the full-reset branch and re-prefills the whole context. Fix:
(a) log when a reset is *caused* by an un-trimmable quantized cache so the cliff
is observable; (b) only quantize threads on the append-only continuation path
(which never trims), leaving trimmable prefix-reuse threads in full precision.

## Test safety net (added FIRST)

- `tests/test_parser.py`, `tests/test_api.py` — existing; cover parser +
  protocol. **Must stay green at every step.**
- `tests/test_continuation.py` — NEW. `_try_continuation`, `_echo_matches`,
  `continuation_tail` golden-byte assertions for both dialects.
- `tests/test_cache.py` — NEW. `reuse_cache` prefix/trim/reset + the quantize
  interaction, against a fake cache.
- `tests/test_tools.py` — NEW. `ToolRunner` dispatch, error surfacing, and the
  new sandbox jail (allow/deny).

## Execution order (risk-ascending)

1. **Spec + branch** ✅
2. **`server/prompting/` split** — existing tests cover it → safest first win,
   validates the pattern.
3. **Characterization tests** for continuation / cache / tools.
4. **`server/` split** (app → core + adapters) + **cache-cliff fix**.
5. **`agent/` split** (the big one) + **sandbox**.
6. **`agent/adapters/ui/tui/` split**.
7. Update `pyproject.toml` (`packages`), `Makefile`, README import paths.

Each step: move code with minimal edits, keep back-compat re-exports, run
`make test` green before committing.
