# Enhancement: skills, plugins, protocols (MCP/A2A/ACP), and /supercharge

Status: **parked / vision** — not scheduled. The platform layer that several
parked ideas converge into. Builds directly on the dispatcher in
[`tools.md`](tools.md).

## The unifying idea

Everything here is "a capability behind a uniform dispatcher": local executable
skills, plugins, MCP tools, and remote A2A/ACP agents are all **skills** with a
card (`name`, `description`, `input_schema`) reachable via the frozen
`dispatch-skill` / `dispatch-status` / `dispatch-cancel` interface. Because the
model's tool surface stays fixed, adding/removing skills never churns the
continuation KV-cache (see tools.md).

## Skills = executable units (not dumb .md)

A skill is a directory, not a markdown blob:

```
<skills-dir>/<skill-name>/
    skill.toml      # manifest: name, description, input_schema, handler, perms
    handler.py|sh   # the code that actually runs
    SKILL.md        # optional human doc / few-shot
```

- Discovered from `~/.kascode/skills/` (global) + `<workdir>/.agent/skills/` (project).
- The dispatcher validates input vs the manifest schema, runs the handler, and
  returns its output as a tool result.
- `.md` is documentation; the **manifest + handler is what executes**.

## Protocols are adapters, not new cores

- **MCP** — an MCP client adapter registers a server's tools as skills.
- **A2A / ACP** — register remote *agents* as skills (delegate a task, poll
  status, collect result) — the async `dispatch-status`/`cancel` lifecycle fits
  agent-to-agent task semantics directly.
- All land in the one registry; the frozen dispatch interface keeps the prompt
  stable.

## Self-authoring (powerful + dangerous)

The agent can write a new skill (manifest + handler) into a skills dir and then
use it. This is **arbitrary, self-authored code execution**, so it MUST be
gated:
- only with `--sandbox` (handlers jailed) + an explicit approval step;
- **test-before-trust**: a new/updated skill runs in a dry-run/validation pass
  before it's allowed in normal turns;
- versioned + revertible (skills dir is git-trackable).

## /supercharge — periodic meta-learning

A batch self-improvement mode, run occasionally (not every turn):

1. Mine session history (already RAG-indexed) for **recurring task patterns**
   and repeated tool-call sequences.
2. Identify capability gaps ("this 6-step dance happens every session").
3. **Synthesize or update skills** to automate them; propose them to the user.
4. Accept → the skills register and are available next session.

Observe → find gaps → build its own tools. The substrate (session memory +
recall) already exists; this adds the meta-loop on top.

## Risks / open questions

- **Security** is the headline: self-authored + remote skills = code execution.
  Sandbox, approval gates, per-skill permissions in the manifest, and an
  allowlist are mandatory.
- **Trust/validation** of agent-written skills (dry-run, tests, rollback).
- **Discovery cost** — discover-then-pin (tools.md) so the skill index doesn't
  re-invalidate the cache each turn.
- **Schema/versioning/conflicts** across skill dirs + remote sources.

## Sequencing (milestones, not one build)

1. Tool registry + `Tool`/skill abstraction (tools.md foundation).
2. Local executable skills + skills dirs + the dispatcher.
3. MCP client adapter (biggest external-capability payoff for least risk).
4. A2A / ACP agent adapters.
5. Guarded self-authoring (sandbox + approval + test-before-trust).
6. `/supercharge` meta-loop.
