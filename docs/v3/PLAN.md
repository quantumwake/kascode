# kas v3 — Remediation Plan

> Execution plan for the issues in [`ANALYSIS.md`](./ANALYSIS.md). All work lands
> on a **single branch `v3`** — no feature branches, no stacked PRs. Each phase is
> a self-contained, independently-revertable set of commits.

---

## Operating principles

1. **One branch.** Everything commits to `v3`. `main` stays frozen until v3 is
   ready to merge as one unit.
2. **Test-before-refactor.** No god-function gets split until a characterization
   test pins its current behaviour. Behaviour-preserving refactors only — if a
   refactor changes output, it's a bug, and the locked test catches it.
3. **Tooling before surgery.** Linting/types/coverage land first so every later
   phase is measured, not asserted.
4. **No file over ~400 lines, no function over ~60 lines** as the exit bar
   (`tui.py` and `agent_turn()` are the explicit violators today).
5. **Each phase ends green** — `make test` (and, after Phase 0, `ruff`/`mypy`)
   pass before the next phase starts.

---

## Phase map

| # | Phase | Goal | Risk | Depends on | Status |
|---|-------|------|------|------------|--------|
| 0 | Tooling foundation | ruff + mypy + pytest + coverage + CI | Low | — | ✅ done |
| 1 | Security quick wins | **sandbox default-on**, `max_tokens` cap, body-size limit | Low | 0 | ✅ done |
| 2 | Test net (pre-refactor) | Characterization tests for the modules about to change | Low | 0 | ✅ done |
| 3 | Decompose `tui.py` | 1,538L → `agent/tui/` package, no file >400L | Medium | 2 | ⬜ next |
| 4 | Split god-functions | `agent_turn`, `on_input_submitted`, `generate`, `cli.main`, `pipeline.run` | High | 2 | ⬜ |
| 5 | Ports hygiene | Formal `AgentIO` conformance; ports for `SessionStore`, `Workspace` | Medium | 4 | ⬜ |
| 6 | Adapter cleanup | Thin `ToolRunner`; decompose `engine.py` | Medium | 5 | ⬜ |

**Progress (v3 branch):** Phase 0 — `14e9bde` (tooling/CI) + `9bb9a38` (strict
reformat). Phase 1 — `bc90d53` (sandbox default-on, max_tokens cap, body limit).
Phase 2 — `af4bf6a` (characterization net: loop, commands, bash, git, bm25,
files-resolver). Lint clean, **14/14 tests green, coverage 32% → 44%**.
`agent_turn()` and `on_input_submitted()` are now behaviour-locked — safe to split.

Order rationale: tooling → safety net → mechanical splits (tui) → risky logical
splits (functions) → structural (ports) → deep adapter work. Tests precede every
refactor.

---

## Phase 0 — Tooling foundation

**Why first:** we're about to move ~2,000 lines of code. Without lint/type/coverage
gates, regressions hide. This phase changes no runtime behaviour.

**Do:**
- Add `[tool.ruff]` + `[tool.mypy]` to `pyproject.toml`; add `pytest`,
  `pytest-cov`, `ruff`, `mypy` to a `dev` optional-dependency group.
- `ruff check --fix` + `ruff format` once to establish a clean baseline (commit
  the reformat separately so logical diffs stay readable later).
- Start mypy permissive (`ignore_missing_imports`, no `strict`); ratchet per phase.
- Add `.github/workflows/ci.yml`: `ruff check`, `mypy`, `pytest` on push/PR. Tests
  already run CPU-only, so CI is free.
- Keep the existing `make test` working; add `make lint`, `make typecheck`, `make cov`.

**Note on test migration:** the 7 scripts are top-level-assert style. Wrap each in
`def test_*()` so pytest collects them (mechanical, behaviour-identical), enabling
`pytest-cov` to replace the report's *guessed* coverage with a real number.

**Exit:** CI green; real coverage % published; `make lint`/`typecheck`/`cov` exist.

---

## Phase 1 — Security quick wins

Small, high-value, low-risk. Lands before refactors so the safety default is in
from the start.

**1a. Sandbox default-on (explicit user directive).**
- `cli.py:142` currently: `--sandbox` `store_true`, default `KAS_SANDBOX=="1"`.
- Change to the existing `--rag` pattern (`argparse.BooleanOptionalAction`):
  ```python
  ap.add_argument("--sandbox", action=argparse.BooleanOptionalAction,
                  default=os.environ.get("KAS_SANDBOX", "1") != "0",
                  help="jail file tools to the workdir (on by default; "
                       "--no-sandbox or KAS_SANDBOX=0 to allow access outside)")
  ```
- This makes file tools jailed-by-default; `--no-sandbox` / `KAS_SANDBOX=0` opts out.
- Update `SandboxViolation`'s message ("re-run without --sandbox" → "re-run with
  `--no-sandbox`"), the README, and `security-assessment.md`'s "off by default" gap.
- **Test:** `test_tools.py` already covers sandbox on/off; add a test asserting the
  *default* resolver (constructed as the CLI now constructs it) rejects `../escape`.
- **Caveat to document:** sandbox constrains file tools, **not bash**. Bash `cd`
  freedom is a separate problem (deferred to a bash-containment follow-up:
  per-command timeout, `ulimit`, optional denylist).

**1b. Cap `max_tokens`.** `schema.py:61` → `max_tokens: int = Field(1024, ge=1, le=...)`
plus an explicit check in `_validate()` so the error uses the Anthropic envelope.

**1c. Request-body size limit.** Add a Starlette middleware (or `Content-Length`
check) capping bodies (e.g. 50 MB) with a clean 413 in the error envelope.

**Deferred (documented, not done here):** optional `KAS_API_KEY` header auth +
startup warning when bound to a non-loopback host. Tracked for a later phase.

**Exit:** sandbox on by default with tests; `max_tokens` and body bounded; docs updated.

---

## Phase 2 — Test net before refactor

**Why:** Phases 3–4 rewrite the highest-branch code in the repo. These tests lock
current behaviour so a behaviour change shows up as a failure.

**Add characterization tests (CPU-only, no model):**
- `test_bash.py` — `BashSession` lifecycle: spawn, run, idle-wait/timeout, exit
  capture, single-session guard. Use a temp dir + trivial commands.
- `test_files_resolver.py` — broaden the sandbox tests incl. the verified
  symlink-escape-is-rejected case (locks the corrected behaviour).
- `test_bm25.py` — `RagIndex` chunking/index/search on a temp corpus (pure, no model).
- `test_git.py` — `GitWorkspace.ready()`/`checkpoint()` in a temp repo.
- `test_loop.py` — drive `agent_turn()` with a **fake Anthropic client** + fake
  `AgentIO`/`ToolExecutor` (the pattern already exists in `test_api.py`/
  `test_continuation.py`): assert the tool-call→result→continue loop, steering
  injection at tool boundary, reconnect path, and stop conditions. **This is the
  prerequisite for Phase 4.**
- `test_commands.py` — table-driven over `on_input_submitted` outcomes (toggles,
  queue puts, dispatch) against a headless `AgentApp`/fake. Prerequisite for the
  command-dispatcher extraction in Phase 3.

**Exit:** every module touched in Phases 3–4 has a behaviour-locking test; coverage
visibly rises off the Phase 0 baseline.

---

## Phase 3 — Decompose `tui.py` (the 1,538-line file)

Mostly mechanical moves (Phase 2 + the structural map de-risk it). Target package:

```
agent/tui/
  __init__.py          # re-exports AgentApp (keeps `agent.tui` import working)
  app.py               # AgentApp: compose/mount/bindings/state + wiring only  (~250L)
  io.py                # TuiIO  (the AgentIO adapter)                            (~110L)
  commands.py          # slash-command registry (extracted from on_input_submitted)
  stats.py             # _stats_line, _gauge, _fmt_bytes, status panel
  model_select.py      # ModelSelect modal + _handle_model_command/_switch_model
  widgets.py           # PasteInput, SelectableRichLog, SubagentView
  loops.py             # _agent_loop + _status_loop worker threads
  fx/
    __init__.py
    bar.py             # FxBar shell: _tick state machine, theme apply  (~150L)
    effects.py         # the 48 effect fns as a registry {name: fn}     (~450L)
    themes.py          # SCREEN_THEMES + palette tables
```

**Method:** move, don't rewrite. Shared `AgentApp` mutable state (`messages`,
`busy`, `fx_mode`, token counters, `subagents`) stays owned by `app.py`; extracted
modules take the app (or the specific state) as a parameter. Effects become a
`dict[str, Callable]` registry so `/fx list` and adding an effect no longer touch a
639-line class.

**Exit:** no file in `agent/tui/` over ~400 lines; `agent.tui` still imports; the
TUI launches and the Phase 2 command tests pass unchanged.

---

## Phase 4 — Split the god-functions

The risky phase — guarded by Phase 2 tests. Each split is behaviour-preserving.

| Function | Now | Split into |
|----------|-----|-----------|
| `agent_turn()` `loop.py:100` | 232L / 60 br | `_stream_response()` (API+retry/reconnect), `_run_tools()` (dispatch loop + tool_result assembly), `_maybe_compact()` (compaction/steering checks), thin `agent_turn` orchestrator |
| `on_input_submitted()` `tui.py:1258` | 153L / 55 br | command registry from Phase 3 — one handler fn per slash command; dispatcher just looks up + calls |
| `generate()` `engine.py:285` | 172L | `_prepare_prompt()` (tokenize/continuation), `_run_decode()` (loop + keep-alive ping), `_persist_kv()` |
| `main()` `cli.py:119` | 167L / 38 br | `_build_parser()`, `_resolve_config()`, `_dispatch(args)` |
| `pipeline.run()` `pipeline.py:31` | 133L | `_setup()` (continuation/tokenize) + `_emit()` (parser→events loop) |

**Method:** extract pure-ish helpers; keep signatures of the public entry points
unchanged so callers and tests don't move. Run the Phase 2 tests after *each*
extraction, not at the end.

**Exit:** no function over ~60 lines / ~20 branches in these files; all Phase 2
tests green; mypy ratcheted up on the touched modules.

---

## Phase 5 — Ports hygiene

Close the §2 architecture gaps now that the modules are small enough to type cleanly.

- **Formalize `AgentIO` conformance.** Make `TuiIO` and `ConsoleIO` explicitly
  satisfy the port: either inherit a `Protocol`-derived ABC, or add a
  startup/test assertion using the already-`@runtime_checkable` `AgentIO`
  (`assert isinstance(io, AgentIO)`), so a missing method fails fast, not mid-run.
- **Add ports for composition deps.** Define `SessionStorePort` and
  `WorkspacePort` (thin Protocols) so `cli.py` wires against interfaces and the
  Phase 2 fakes have a declared contract. This is what makes `filesystem.py` and
  `git.py` properly testable rather than incidentally so.
- Add a CI guard (simple import-lint / grep) that fails if anything under `*/core/`
  imports `*/adapters/*` — locks the property that currently holds by discipline.

**Exit:** UI port conformance is enforced; the two composition deps have ports;
the core-isolation invariant is machine-checked.

---

## Phase 6 — Adapter cleanup (deepest, lowest urgency)

- **Slim `ToolRunner`** (executor.py, 312L): split tool *dispatch* (a registry)
  from per-tool glue; each tool group (`files`, `bash`, `recall`, `web`, `image`)
  becomes a small registered handler. Lets each be unit-tested without the whole runner.
- **Decompose `engine.py`** (547L) along the lines its own docstring already implies:
  `kv_cache.py` (slot mgmt + quantization), `loader.py` (load/swap/detect),
  `worker.py` (thread loop + job queue), leaving `engine.py` as the `EngineLike`
  facade. Note this stays GPU-bound and largely untestable in CI — split for
  readability, not coverage.

**Exit:** no adapter file over ~400 lines; tool handlers individually testable.

---

## Definition of done (whole branch)

- [ ] Sandbox **on by default**; `--no-sandbox` opt-out; tested.
- [ ] `max_tokens` capped; request body bounded.
- [ ] No source file over ~400 lines (`tui.py` gone as a monolith).
- [ ] No function over ~60 lines / ~20 branches in core/loop, tui, engine, cli, pipeline.
- [ ] Characterization tests exist for every module that was refactored.
- [ ] `AgentIO` conformance enforced; `SessionStore`/`Workspace` ported; core-isolation CI guard.
- [ ] `ruff` + `mypy` + `pytest` green in CI; real coverage number published and up.
- [ ] One branch (`v3`), behaviour-preserving throughout — the app runs identically.

---

## Explicitly deferred (not in v3 unless asked)

- Optional `KAS_API_KEY` auth + non-loopback bind warning.
- Bash containment (per-command timeout, `ulimit`, denylist).
- `pip-audit`/Dependabot supply-chain scanning.
- KV-cache integrity check on resume; `--bench` mode.

These are real (from the security/functionality reports) but orthogonal to the
"sandbox-default + modularize + test" mandate driving v3.
