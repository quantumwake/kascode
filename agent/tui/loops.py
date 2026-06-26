"""The TUI's two worker threads, as a mixin on AgentApp: _agent_loop drains the
message queue and runs core.agent_turn (handling steering, errors, session save,
pause-exit); _status_loop polls GET /v1/stats once a second to drive the status
bar and the ambient fx. Mixed into AgentApp, so `self` is the app.
"""

import time

import anthropic
import httpx
from rich.text import Text

from agent import main as core


class WorkerLoops:
    def _agent_loop(self) -> None:
        messages = self.messages
        while True:
            task = self.msg_q.get()
            if task is None:
                return
            self.busy = True
            try:
                if task == "\x00compact":
                    extra = (core.RAG_TOOLS if self.runner.rag else []) + (
                        core.WEB_TOOLS if self.runner.net else []
                    )
                    core.compact_messages(
                        self.client,
                        messages,
                        self.io,
                        self.model,
                        store=self.store,
                        max_tokens=self.max_tokens,
                        tools=core.TOOLS + [core.SUBAGENT_TOOL] + extra,
                    )
                    continue
                if task == "\x00self-skill":
                    core.self_skill(
                        self.client, self.io, self.model, self.workdir, max_tokens=self.max_tokens
                    )
                    continue
                if task == "\x00ai-wellbeing":
                    core.assess_wellbeing(
                        self.client,
                        self.io,
                        messages,
                        self.model,
                        self.workdir,
                        max_tokens=self.max_tokens,
                    )
                    continue
                if task == "\x00continue":
                    # resume a mid-task session: if the model owes a turn, just
                    # run; if the last turn was the agent's, nudge it onward.
                    if messages and messages[-1].get("role") == "assistant":
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "[resumed] Continue the task from exactly where you left off."
                                ),
                            }
                        )
                else:
                    messages.append({"role": "user", "content": task})
                core.agent_turn(
                    self.client,
                    messages,
                    self.runner,
                    self.io,
                    model=self.model,
                    max_tokens=self.max_tokens,
                    store=self.store,
                    viz=self.viz.header(),
                )
                # steering submitted after the final response starts a new turn
                leftovers = self.io.drain_steers()
                while leftovers:
                    messages.append({"role": "user", "content": "\n".join(leftovers)})
                    core.agent_turn(
                        self.client,
                        messages,
                        self.runner,
                        self.io,
                        model=self.model,
                        max_tokens=self.max_tokens,
                        store=self.store,
                    )
                    leftovers = self.io.drain_steers()
            except anthropic.APIError as exc:
                self.io.notice(f"[api error] {exc}")
            except Exception as exc:  # keep the UI alive on agent bugs
                self.io.notice(f"[error] {type(exc).__name__}: {exc}")
            finally:
                self.busy = False
                self.turns = len(messages)
                paused = self.io.pause.is_set()
                if messages:
                    try:
                        self.store.save_transcript(messages, self.model, paused=paused)
                    except Exception as exc:
                        self.io.notice(f"[session save failed] {exc}")
                if paused:
                    self.call_from_thread(
                        self.body_write,
                        Text(f"[paused · resume: kas --resume {self.store.id}]", style="#ffb000"),
                    )
                    self.call_from_thread(self.exit)
                    return  # noqa: B012  — pause path intentionally exits the worker loop

    def _status_loop(self) -> None:
        url = self.base_url.rstrip("/") + "/v1/stats"
        online = True  # last known server reachability (for transition notices)
        while self._alive:
            try:
                s = httpx.get(url, timeout=2).json()
                up = True
            except Exception:
                s, up = {}, False
            # announce reachability transitions in the work view (reconnect mark)
            if up != online:
                try:
                    self.call_from_thread(
                        self.body_write,
                        Text(
                            "● reconnected to server" if up else "○ server unreachable — retrying…",
                            style="#3fb950" if up else "#ff5f5f",
                        ),
                    )
                except Exception:
                    return
                online = up
            age = s.get("last_ping_age")
            ping = ""
            if s.get("active") and age is not None:
                ping = f" · ping {age:g}s ago"
            stale = age is not None and age > 20  # pings should arrive ~every 5s
            if not up:
                conn, conn_style, work, mode = (
                    "○ offline",
                    "#ff5f5f",
                    "server unreachable",
                    "offline",
                )
            elif s.get("active") and s.get("phase") == "prefill":
                conn = "◓ prefill" if not stale else "◓ prefill ⚠"
                conn_style = "#ffa657" if not stale else "#ff5f5f"  # amber, red if pings stalled
                work = (
                    f"{s.get('processed', 0)}/{s.get('total', '?')} tok "
                    f"(cache {s.get('cached', 0)}) · {s.get('elapsed', 0):.0f}s{ping}"
                )
                mode = "prefill"
            elif s.get("active"):
                conn = "◉ streaming" if not stale else "◉ streaming ⚠"
                conn_style = "#39d3e8" if not stale else "#ff5f5f"  # cyan, red if pings stalled
                work = (
                    f"{s.get('generated', 0)} tok @ {s.get('tps', 0)} tok/s "
                    f"· {s.get('elapsed', 0):.0f}s{ping}"
                )
                mode = "generating"
            elif self.busy:
                conn, conn_style, work, mode = (
                    "◌ tools",
                    "#c792ea",
                    "running tools",
                    "tools",
                )  # violet
            else:
                conn, conn_style, work, mode = "● live", "#3fb950", "idle", "idle"  # green
            self.fx_mode = mode  # drive the ambient FxBar animation by current state
            self.fx_stats = {
                "tps": s.get("tps"),
                "processed": s.get("processed"),
                "total": s.get("total"),
                "ping_age": age,
            }
            line = Text()
            line.append(conn + " ", style=conn_style)
            line.append(f"· {self.model} · yolo {'ON' if self.runner.yolo else 'off'} · {work}")
            queued = self.io.steer_q.qsize()
            if queued:
                line.append(f" · steering queued: {queued}")
            if self.subagents:
                running = sum(1 for a in self.subagents if a.status == "running")
                line.append(
                    f" · subagents: {len(self.subagents)}"
                    + (f" ({running} running)" if running else "")
                )
            if self.tok_in or self.tok_out:  # cumulative token counter
                line.append(f" · {self._token_summary()}", style="#c792ea")
            try:
                self.call_from_thread(self.update_status, line)
                if self.stats_on:
                    self.call_from_thread(self._update_topstats, self._stats_line(s))
            except Exception:
                return
            time.sleep(1.0)
