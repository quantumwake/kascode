"""/model [<id>|<n>] — show the model picker, or hot-swap by id/number."""

import threading
import time

import httpx
from rich.text import Text

from scripts.select_model import downloaded_models

from ..widgets import ModelSelect
from .base import Command


class ModelCommand(Command):
    name = "/model"
    summary = "switch the served model (picker, or by id / number)"
    usage = "[<id>|<n>]"

    def match(self, text: str) -> str | None:
        # historical prefix match (so "/model gemma" and "/model" both route here)
        return text[len(self.name) :].strip() if text.startswith(self.name) else None

    def run(self, app, arg: str) -> None:
        models = downloaded_models()
        if not models:
            app.body_write(Text("no downloaded models — make download MODEL=…", style="yellow"))
            return
        if not arg:
            # interactive picker
            def chosen(target: str | None) -> None:
                if target and target != app.model:
                    self._switch(app, target)

            app.push_screen(ModelSelect(models, app.model), chosen)
            return
        # direct switch by id or list number
        if arg.isdigit() and 1 <= int(arg) <= len(models):
            target = models[int(arg) - 1]
        elif arg in models:
            target = arg
        else:
            app.body_write(Text(f"unknown model {arg!r} — /model to pick", style="red"))
            return
        if target == app.model:
            app.body_write(Text(f"already serving {target}", style="yellow"))
            return
        self._switch(app, target)

    @staticmethod
    def _switch(app, target: str) -> None:
        from scripts.select_model import model_info

        info = {m["id"]: m for m in model_info()}
        cur, tgt = info.get(app.model, {}), info.get(target, {})
        app.body_write(
            Text(
                f"[switching {app.model.split('/')[-1]} ({cur.get('size_h', '?')}) → "
                f"{target.split('/')[-1]} ({tgt.get('size_h', '?')}) — offloads the current "
                "model, then loads the new one…]",
                style="yellow",
            )
        )

        # Live loading indicator: a big model (tens of GB) loads for a minute+
        # with no other signal, so the swap LOOKS frozen. Drive the progress-bar
        # fx + an elapsed counter until the (synchronous) load returns.
        done = threading.Event()
        t0 = time.monotonic()
        short = target.split("/")[-1]

        def loading_fx() -> None:
            while not done.wait(1.0):
                el = int(time.monotonic() - t0)
                app.fx_override = {
                    "mode": "prefill",  # the progress-bar animation
                    "conn": "⟳ loading model",
                    "style": "#ffa657",
                    "work": f"{short} · {el}s (large models take a minute+)",
                }

        def do_swap() -> None:
            app.fx_override = {
                "mode": "prefill",
                "conn": "⟳ loading model",
                "style": "#ffa657",
                "work": f"{short} · 0s",
            }
            threading.Thread(target=loading_fx, daemon=True).start()
            try:
                resp = httpx.post(
                    app.base_url.rstrip("/") + "/v1/models/select",
                    json={"model": target},
                    timeout=900,
                ).json()
                if resp.get("ok"):
                    app.model = resp["model"]
                    # New model -> new decode speed; forget the old baseline so the
                    # relative compaction trigger re-learns it.
                    app.runner.tps_baseline = 0.0
                    app.runner.tps_window.clear()
                    el = int(time.monotonic() - t0)
                    note = f"[now serving {resp['model']} (dialect: {resp.get('dialect')}) · {el}s]"
                else:
                    note = f"[swap failed: {resp.get('error', {}).get('message', resp)}]"
            except Exception as exc:
                note = f"[swap failed: {exc}]"
            finally:
                done.set()
                app.fx_override = None  # release the indicator
            try:
                app.call_from_thread(app.body_write, Text(note, style="yellow"))
            except Exception:
                pass

        threading.Thread(target=do_swap, daemon=True).start()
