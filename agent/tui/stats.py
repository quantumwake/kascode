"""The /stats panel + status-bar rendering for the TUI, as a mixin on AgentApp:
the docked stats line (context gauge, GPU mem, tok/s, cumulative tokens, and
psutil CPU/RAM/IO rates) plus small formatting helpers. Mixed into AgentApp.
"""

import time

from rich.text import Text
from textual.widgets import Static

try:
    import psutil  # optional ('stats' extra)
except ImportError:
    psutil = None


class StatsPanel:
    def update_status(self, line: str) -> None:
        self.query_one("#status", Static).update(line)

    # ---- /stats panel ----

    @staticmethod
    def _fmt_bytes(n: float) -> str:
        n = float(n)
        for u in ("B", "K", "M", "G"):
            if n < 1024 or u == "G":
                return f"{n:.0f}{u}" if u in ("B", "K") else f"{n:.1f}{u}"
            n /= 1024
        return f"{n:.1f}G"

    @staticmethod
    def _fmt_tok(n) -> str:
        n = int(n or 0)
        return str(n) if n < 1000 else f"{n / 1000:.1f}k"

    def _token_summary(self) -> str:
        """Compact cumulative token counter for the status bar (cached shown only
        when the server reports it)."""
        s = f"tok {self._fmt_tok(self.tok_in)}↑ {self._fmt_tok(self.tok_out)}↓"
        if self.tok_cache_read:
            s += f" {self._fmt_tok(self.tok_cache_read)}⚡"
        return s

    @staticmethod
    def _gauge(frac: float, width: int = 6) -> Text:
        frac = max(0.0, min(1.0, frac))
        filled = int(round(frac * width))
        color = "#3fb950" if frac < 0.7 else ("#ffa657" if frac < 0.9 else "#ff5f5f")
        t = Text("▕", style="#555555")
        t.append("█" * filled + "░" * (width - filled), style=color)
        t.append("▏", style="#555555")
        return t

    def _stats_line(self, s: dict | None) -> Text:
        s = s or {}
        L, V, C = "#8a6a2a", "#ffb000", "#39d3e8"  # label / value / accent colours
        t = Text()
        t.append("▌ ", style="#ff9d00")
        t.append(self.model.split("/")[-1], style="bold #ffb000")
        t.append("  ")
        # context window usage
        cl = s.get("context_length") or getattr(self.runner, "context_limit", None)
        used = getattr(self.runner, "last_input_tokens", 0)
        if cl:
            t.append("ctx ", style=L)
            t.append_text(self._gauge(used / cl))
            t.append(f" {used // 1000}k/{cl // 1000}k  ", style=V)
        if s.get("layers"):
            t.append("layers ", style=L)
            t.append(f"{s['layers']}  ", style=V)
        # GPU memory
        ga, gp = s.get("gpu_active_gb"), s.get("gpu_peak_gb")
        if ga is not None:
            t.append("gpu ", style=L)
            if gp:
                t.append_text(self._gauge(ga / gp if gp else 0))
            t.append(f" {ga}/{gp}GB  " if gp else f" {ga}GB  ", style=C)
            gu = s.get("gpu_util")
            if gu is not None:
                t.append(f"{gu}% util  ", style=C)
        if s.get("tps"):
            t.append("tok/s ", style=L)
            t.append(f"{s['tps']}  ", style=C)
        t.append("Σ ", style=L)
        cached = f" · cached {self._fmt_tok(self.tok_cache_read)}" if self.tok_cache_read else ""
        t.append(
            f"in {self._fmt_tok(self.tok_in)} · out {self._fmt_tok(self.tok_out)}{cached} · "
            f"total {self._fmt_tok(self.tok_in + self.tok_out)}  ",
            style="#c792ea",
        )
        # system metrics (optional psutil)
        if psutil is None:
            t.append("(uv add psutil for cpu/ram/io)", style="#555555")
            return t
        try:
            cpu = psutil.cpu_percent()
            t.append("cpu ", style=L)
            t.append_text(self._gauge(cpu / 100))
            t.append(f" {cpu:.0f}%  ", style=V)
            vm = psutil.virtual_memory()
            t.append("ram ", style=L)
            t.append_text(self._gauge(vm.percent / 100))
            t.append(f" {self._fmt_bytes(vm.used)}/{self._fmt_bytes(vm.total)}  ", style=V)
            d, n, now = psutil.disk_io_counters(), psutil.net_io_counters(), time.time()
            dtot = (d.read_bytes + d.write_bytes) if d else 0
            ntot = (n.bytes_sent + n.bytes_recv) if n else 0
            if self._io_prev:
                pd, pn, pt = self._io_prev
                dt = max(0.1, now - pt)
                t.append("disk ", style=L)
                t.append(f"{self._fmt_bytes((dtot - pd) / dt)}/s  ", style="#8a8a8a")
                t.append("net ", style=L)
                t.append(f"{self._fmt_bytes((ntot - pn) / dt)}/s", style="#8a8a8a")
            self._io_prev = (dtot, ntot, now)
        except Exception:
            pass
        return t

    # ---- input routing ----

    def _update_topstats(self, txt: Text) -> None:
        """Update the top stats panel; runs on the UI thread (via call_from_thread)."""
        self.query_one("#topstats", Static).update(txt)
