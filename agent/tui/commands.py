"""Slash-command dispatch + model switching for the TUI, as a mixin on AgentApp.

on_input_submitted routes every submitted line: confirmations, /commands, exit,
and — when busy — steering vs (when idle) a new turn. The widget-backed commands
(/fx, /theme, /stats, /model, /subagents) live here too. Mixed into AgentApp, so
`self` is the app.
"""

import threading

import httpx
from rich.text import Text
from textual.widgets import Input

from scripts.select_model import downloaded_models

from .fx import FxBar
from .widgets import ModelSelect, SubagentView


class CommandHandler:
    def _handle_model_command(self, arg: str) -> None:
        models = downloaded_models()
        if not models:
            self.body_write(Text("no downloaded models — make download MODEL=…", style="yellow"))
            return
        if not arg:
            # interactive picker
            def chosen(target: str | None) -> None:
                if target and target != self.model:
                    self._switch_model(target)

            self.push_screen(ModelSelect(models, self.model), chosen)
            return
        # direct switch by id or list number
        if arg.isdigit() and 1 <= int(arg) <= len(models):
            target = models[int(arg) - 1]
        elif arg in models:
            target = arg
        else:
            self.body_write(Text(f"unknown model {arg!r} — /model to pick", style="red"))
            return
        if target == self.model:
            self.body_write(Text(f"already serving {target}", style="yellow"))
            return
        self._switch_model(target)

    def _switch_model(self, target: str) -> None:
        from scripts.select_model import model_info

        info = {m["id"]: m for m in model_info()}
        cur, tgt = info.get(self.model, {}), info.get(target, {})
        self.body_write(
            Text(
                f"[switching {self.model.split('/')[-1]} ({cur.get('size_h', '?')}) → "
                f"{target.split('/')[-1]} ({tgt.get('size_h', '?')}) — offloads the current "
                "model, then loads the new one…]",
                style="yellow",
            )
        )

        def do_swap() -> None:
            try:
                resp = httpx.post(
                    self.base_url.rstrip("/") + "/v1/models/select",
                    json={"model": target},
                    timeout=900,
                ).json()
                if resp.get("ok"):
                    self.model = resp["model"]
                    note = f"[now serving {resp['model']} (dialect: {resp.get('dialect')})]"
                else:
                    note = f"[swap failed: {resp.get('error', {}).get('message', resp)}]"
            except Exception as exc:
                note = f"[swap failed: {exc}]"
            try:
                self.call_from_thread(self.body_write, Text(note, style="yellow"))
            except Exception:
                pass

        threading.Thread(target=do_swap, daemon=True).start()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        # confirmations and slash-commands act on the typed line only; staged
        # pastes (if any) stay staged for the next real message.
        if self.confirming:
            self.io.confirm_q.put(text)
            return
        if not text and not self._pastes:
            return
        if text in ("exit", "quit"):
            self.exit()
            return
        if text.startswith("/") and not self._pastes:
            if text == "/stop":
                self.action_interrupt()
            elif text == "/pause":
                self.action_pause()
            elif text.startswith("/model"):
                self._handle_model_command(text[len("/model") :].strip())
            elif text == "/compact":
                if self.busy:
                    self.body_write(
                        Text("[/compact: wait until the agent is idle]", style="yellow")
                    )
                elif not self.messages:
                    self.body_write(Text("[nothing to compact yet]", style="yellow"))
                else:
                    self.msg_q.put("\x00compact")
            elif text == "/self-skill":
                if self.busy:
                    self.body_write(
                        Text("[/self-skill: wait until the agent is idle]", style="yellow")
                    )
                else:
                    self.msg_q.put("\x00self-skill")
                return
            elif text == "/yolo":
                self.runner.yolo = not self.runner.yolo
                state = (
                    "ON — commands run without confirmation"
                    if self.runner.yolo
                    else "OFF — commands need approval"
                )
                self.body_write(Text(f"yolo {state}", style="yellow"))
            elif text.startswith("/subagent"):
                rest = text[len("/subagent") :].lstrip()
                # /subagents (list)  ·  /subagent N (drill in)
                if rest.lstrip("s").strip() == "" and not rest[:1].isdigit():
                    if not self.subagents:
                        self.body_write(Text("no subagents spawned this session", style="yellow"))
                    else:
                        self.body_write(Text("subagents:", style="yellow"))
                        for s in self.subagents:
                            self.body_write(
                                Text(f"  [{s.n}] {s.status:<7} {s.label}", style="yellow")
                            )
                        self.body_write(Text("open one with /subagent <n>", style="yellow"))
                else:
                    arg = rest.lstrip("s").strip()
                    match = next((s for s in self.subagents if str(s.n) == arg), None)
                    if match:
                        self.push_screen(SubagentView(match))
                    else:
                        self.body_write(
                            Text(f"no subagent {arg!r} — /subagents to list", style="red")
                        )
            elif text == "/fx" or text.startswith("/fx "):
                arg = text[len("/fx") :].strip().lower()
                fx = self.query_one("#fx")
                if arg in ("", "toggle"):
                    fx.display = not fx.display
                    msg = f"fx {'on' if fx.display else 'off'}"
                elif arg == "on":
                    fx.display = True
                    msg = "fx on"
                elif arg == "off":
                    fx.display = False
                    msg = "fx off"
                elif arg in ("auto", "reset"):
                    fx._pin = None
                    fx.display = True
                    msg = "fx auto (reacts to state)"
                elif arg in ("list", "?"):
                    msg = "fx: " + ", ".join(FxBar.EFFECTS) + " · auto · on · off"
                elif arg in FxBar.EFFECTS:
                    fx._pin = arg
                    fx.display = True
                    msg = f"fx pinned: {arg}  (/fx auto to unpin)"
                else:
                    msg = f"unknown fx {arg!r} — try /fx list"
                self.body_write(Text(msg, style="yellow"))
                return
            elif text == "/theme" or text.startswith("/theme "):
                fx = self.query_one("#fx")
                fx.display = True
                arg = text[len("/theme") :].strip().lower()
                # reskin the whole screen too: a named theme repaints chrome; auto
                # falls back to the default amber chrome (fx then rotates colours).
                if arg in self.SCREEN_THEMES:
                    self.theme = arg
                elif arg in ("auto", "off", "none"):
                    self.theme = "amber"
                self.body_write(Text(fx.set_theme(arg), style="yellow"))
                return
            elif text.startswith("/rag"):
                arg = text[len("/rag") :].strip().lower()
                if arg in ("enable", "on"):
                    self.runner.rag = True
                elif arg in ("disable", "off"):
                    self.runner.rag = False
                elif arg:
                    self.body_write(Text("usage: /rag [enable|disable]", style="yellow"))
                    return
                self.body_write(
                    Text(
                        "recall ENABLED — local code/docs/memory search available"
                        if self.runner.rag
                        else "recall DISABLED",
                        style="yellow",
                    )
                )
            elif text == "/stats":
                panel = self.query_one("#topstats")
                panel.display = not panel.display
                self.stats_on = panel.display
                self.body_write(
                    Text(f"stats panel {'on' if panel.display else 'off'}", style="yellow")
                )
                return
            elif text == "/ctx" or text.startswith("/ctx "):
                from agent.core.compaction import ctx_command

                self.body_write(Text(ctx_command(self.runner, text[len("/ctx") :]), style="yellow"))
                return
            elif text == "/kv" or text.startswith("/kv "):
                self.body_write(Text(self.runner.kv_status(text[len("/kv") :]), style="yellow"))
                return
            elif text == "/art":
                self.runner.art = not self.runner.art
                state = "ENABLED — generate_image available" if self.runner.art else "DISABLED"
                self.body_write(
                    Text(
                        f"image generation {state} (needs the 'art' extra: uv add mflux)",
                        style="yellow",
                    )
                )
                return
            elif text == "/status":
                self.body_write(
                    Text(
                        f"model={self.model}  yolo={self.runner.yolo}  rag={self.runner.rag}  "
                        f"net={self.runner.net}  workdir={self.workdir}  turns={self.turns}",
                        style="yellow",
                    )
                )
            else:
                self.body_write(
                    Text(
                        "commands: /yolo  /rag [enable|disable]  /ctx [<n>|max|auto]  /subagents  "
                        "/subagent <n>  /status  /compact  /self-skill  /model  /fx  /theme  "
                        "/stop (Esc)  /pause (^P) · exit",
                        style="yellow",
                    )
                )
            return
        # attach staged multiline paste(s): typed instruction first, blob after
        if self._pastes:
            blob = "\n\n".join(self._pastes)
            self._pastes = []
            text = f"{text}\n\n{blob}" if text else blob
        if self.busy:
            self.io.steer_q.put(text)
            self.body_write(
                Text("[queued steering — applies at the next tool boundary]", style="magenta")
            )
        else:
            preview = text.splitlines()[0][:80] + (" …" if "\n" in text or len(text) > 80 else "")
            self.body_write(Text(f"\nyou> {preview}", style="bold"))
            self.msg_q.put(text)

    # ---- worker threads ----
