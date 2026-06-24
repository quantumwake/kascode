"""FxBar's ambient effect renderers, split out as a mixin.

Each effect is a method (self, w, shades) -> Text painting one frame from the
shared scratch buffers (self._cells / _glyphs / _stars) and clock (self._t),
dispatched by name from FxBar._tick. Mixed into FxBar (see bar.py).
"""

import math
import random

from rich.text import Text


class FxEffects:
    GLYPHS = "·✦*°⋆+•∙"
    BARS = " ▁▂▃▄▅▆▇█"
    BRAILLE = " ⠁⠃⠇⡇⣇⣧⣷⣿"

    def _twinkle(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or len(self._glyphs) != w:
            self._cells = [0.0] * w
            self._glyphs = [" "] * w
        for i in range(w):
            self._cells[i] *= 0.82  # fade
        for _ in range(max(1, w // 50)):  # spawn a few new sparks
            i = random.randrange(w)
            self._cells[i] = 1.0
            self._glyphs[i] = random.choice(self.GLYPHS)
        t = Text()
        for i in range(w):
            v = self._cells[i]
            t.append(" " if v < 0.12 else self._glyphs[i], style=shades[min(4, int(v * 5))])
        return t

    def _wave(self, w: int, shades: list[str]) -> Text:
        # speed tracks live decode rate — fast generation visibly rips
        tps = self._stats().get("tps") or 12
        spd = 0.12 + min(40.0, float(tps)) / 40.0 * 0.4
        t = Text()
        for col in range(w):
            y = (
                math.sin(col * 0.25 + self._t * spd) * 0.5
                + math.sin(col * 0.07 - self._t * 0.13) * 0.5
            )
            idx = max(0, min(len(self.BARS) - 1, int((y + 1) / 2 * (len(self.BARS) - 1))))
            t.append(self.BARS[idx], style=shades[1 + (idx * 3) // len(self.BARS)])
        return t

    def _comet(self, w: int, shades: list[str]) -> Text:
        pos = (self._t * 2) % (w + 24) - 12
        t = Text()
        for i in range(w):
            d = abs(i - pos)
            t.append(" " if d > 6 else ("═" if d <= 2 else "─"), style=shades[max(0, 4 - d)])
        return t

    def _pulse(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            b = (math.sin(self._t * 0.12 + col * 0.06) + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _flat(self, w: int, shades: list[str]) -> Text:
        on = (self._t // 6) % 2 == 0
        return Text("".join("·" if (i % 6 == 0 and on) else " " for i in range(w)), style=shades[1])

    def _plasma(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = (
                math.sin(col * 0.20 + self._t * 0.10)
                + math.sin(col * 0.07 - self._t * 0.07)
                + math.sin((col + self._t) * 0.13)
            ) / 3
            b = (v + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _scanline(self, w: int, shades: list[str]) -> Text:
        head = (self._t * 1.5) % (w + 1)
        t = Text()
        for i in range(w):
            d = abs(i - head)
            if d < 1.5:
                ch, sh = "█", 4
            elif d < 4:
                ch, sh = "▓", 3
            elif d < 8:
                ch, sh = "░", 2
            else:
                ch, sh = ("·" if i % 5 == 0 else " "), 0
            t.append(ch, style=shades[sh])
        return t

    def _fire(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w:
            self._cells = [0.0] * w
        for i in range(w):
            self._cells[i] = max(0.0, self._cells[i] * 0.7 + random.uniform(-0.08, 0.08))
            if random.random() < 0.15:
                self._cells[i] = random.random()
        t = Text()
        for v in self._cells:
            idx = min(len(self.BARS) - 1, int(v * (len(self.BARS) - 1)))
            t.append(self.BARS[idx], style=shades[min(4, int(v * 5))])
        return t

    def _starfield(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or not self._stars:
            self._cells = [0.0] * w
            self._stars = [
                [random.uniform(0, w), random.uniform(0.2, 1.0)] for _ in range(max(3, w // 12))
            ]
        glyph = [" "] * w
        sh = [0] * w
        for s in self._stars:
            s[0] += s[1] * 0.6  # drift; brighter (nearer) stars move faster
            if s[0] >= w:
                s[0], s[1] = 0.0, random.uniform(0.2, 1.0)
            i = int(s[0])
            if 0 <= i < w:
                glyph[i] = random.choice(self.GLYPHS) if s[1] > 0.7 else "·"
                sh[i] = min(4, int(s[1] * 5))
        t = Text()
        for ch, s in zip(glyph, sh, strict=False):
            t.append(ch, style=shades[s])
        return t

    def _braille(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            y = (
                math.sin(col * 0.3 + self._t * 0.25) * 0.5
                + math.sin(col * 0.1 - self._t * 0.1) * 0.5
            )
            idx = max(0, min(len(self.BRAILLE) - 1, int((y + 1) / 2 * (len(self.BRAILLE) - 1))))
            t.append(self.BRAILLE[idx], style=shades[1 + (idx * 3) // len(self.BRAILLE)])
        return t

    def _progress(self, w: int, shades: list[str]) -> Text:
        # real prefill progress when the server reports processed/total; else a
        # gentle indeterminate sweep.
        s = self._stats()
        total, done = s.get("total") or 0, s.get("processed") or 0
        t = Text()
        if total:
            fill = int(done / total * w)
            for i in range(w):
                if i < fill:
                    t.append("█", style=shades[3])
                elif i == fill:
                    t.append("▌", style=shades[4])
                else:
                    t.append("·" if i % 4 == 0 else " ", style=shades[1])
        else:
            head = (self._t * 1.2) % (w + 8)
            for i in range(w):
                t.append(
                    "█" if abs(i - head) < 3 else ("·" if i % 4 == 0 else " "),
                    style=shades[3 if abs(i - head) < 3 else 1],
                )
        return t

    def _heartbeat(self, w: int, shades: list[str]) -> Text:
        # a traveling EKG spike over a dim baseline
        pos = int(self._t) % w if w else 0
        t = Text()
        for i in range(w):
            d = (i - pos) % w
            if d == 0:
                ch, sh = "█", 4
            elif d == 1:
                ch, sh = "▆", 3
            elif d == 2:
                ch, sh = "▂", 2
            else:
                ch, sh = "─", 1
            t.append(ch, style=shades[sh])
        return t

    def _larson(self, w: int, shades: list[str]) -> Text:
        # Cylon/KITT scanner — a bright dot bouncing L↔R with a trailing glow.
        period = max(1, 2 * (w - 1))
        p = self._t % period
        pos = p if p < w else period - p
        glyph = {0: "█", 1: "▓", 2: "▒", 3: "░"}
        t = Text()
        for i in range(w):
            d = abs(i - pos)
            t.append(glyph.get(d, " "), style=shades[max(0, 4 - d)])
        return t

    def _bounce(self, w: int, shades: list[str]) -> Text:
        period = max(1, 2 * (w - 1))
        p = self._t % period
        pos = p if p < w else period - p
        t = Text()
        for i in range(w):
            t.append(
                "●" if i == pos else ("·" if i % 8 == 0 else " "),
                style=shades[4 if i == pos else 1],
            )
        return t

    def _vu(self, w: int, shades: list[str]) -> Text:
        # random equalizer bars that jump and decay (music-meter feel)
        if len(self._cells) != w:
            self._cells = [0.0] * w
        for i in range(w):
            self._cells[i] = max(0.0, self._cells[i] - 0.12)
            if random.random() < 0.10:
                self._cells[i] = random.random()
        t = Text()
        for v in self._cells:
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _dna(self, w: int, shades: list[str]) -> Text:
        # two interleaved strands
        t = Text()
        for col in range(w):
            a = math.sin(col * 0.3 + self._t * 0.15)
            b = math.sin(col * 0.3 + self._t * 0.15 + math.pi)
            ya = int((a + 1) / 2 * (len(self.BARS) - 1))
            yb = int((b + 1) / 2 * (len(self.BARS) - 1))
            if ya >= yb:
                t.append(self.BARS[ya], style=shades[3])
            else:
                t.append(self.BARS[yb], style=shades[2])
        return t

    def _ripple(self, w: int, shades: list[str]) -> Text:
        c = w // 2
        t = Text()
        for i in range(w):
            d = abs(i - c)
            v = (math.sin(d * 0.6 - self._t * 0.3) + 1) / 2
            v *= max(0.15, 1 - d / (w / 1.5 or 1))
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _rain(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or len(self._glyphs) != w:
            self._cells = [0.0] * w
            self._glyphs = [" "] * w
        for i in range(w):
            self._cells[i] *= 0.75
        for _ in range(max(1, w // 28)):
            i = random.randrange(w)
            self._cells[i] = 1.0
            self._glyphs[i] = random.choice("╷│┃╿")
        t = Text()
        for i in range(w):
            v = self._cells[i]
            t.append(" " if v < 0.15 else self._glyphs[i], style=shades[min(4, int(v * 5))])
        return t

    def _marquee(self, w: int, shades: list[str]) -> Text:
        pat = "▰▰▱ "
        off = self._t % len(pat)
        t = Text()
        for i in range(w):
            ch = pat[(i + off) % len(pat)]
            t.append(ch, style=shades[3 if ch == "▰" else 1])
        return t

    def _glitch(self, w: int, shades: list[str]) -> Text:
        chars = "▚▞▌▐░▒█┃╳"
        t = Text()
        for i in range(w):
            if random.random() < 0.08:
                t.append(random.choice(chars), style=shades[random.randint(2, 4)])
            else:
                t.append("·" if i % 7 == 0 else " ", style=shades[1])
        return t

    def _sine(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            y = (math.sin(col * 0.2 + self._t * 0.2) + 1) / 2
            t.append(
                "•" if y > 0.55 else ("·" if y > 0.2 else " "), style=shades[min(4, int(y * 5))]
            )
        return t

    def _meteor(self, w: int, shades: list[str]) -> Text:
        pos = (self._t * 2) % (w + 30) - 15
        t = Text()
        for i in range(w):
            d = pos - i  # tail trails to the left
            if d == 0:
                t.append("◉", style=shades[4])
            elif 0 < d < 12:
                t.append("═" if d < 2 else "─", style=shades[max(0, 4 - d // 3)])
            else:
                t.append(" ")
        return t

    def _snake(self, w: int, shades: list[str]) -> Text:
        seg = 8
        head = self._t % w if w else 0
        t = Text()
        for i in range(w):
            d = (head - i) % w
            t.append(
                "█" if d < seg else " ", style=shades[max(0, 4 - d // 2)] if d < seg else shades[0]
            )
        return t

    # --- second wave of effects -------------------------------------------

    def _spectrum(self, w: int, shades: list[str]) -> Text:
        n = len(shades)
        t = Text()
        for i in range(w):
            k = (i + self._t) % (2 * n - 2)
            t.append("█", style=shades[k if k < n else 2 * n - 2 - k])
        return t

    def _wipe(self, w: int, shades: list[str]) -> Text:
        period = max(1, 2 * w)
        p = self._t % period
        edge = p if p < w else period - p
        t = Text()
        for i in range(w):
            t.append(
                "█" if i < edge else ("▌" if i == edge else " "),
                style=shades[4 if i == edge else (3 if i < edge else 0)],
            )
        return t

    def _binary(self, w: int, shades: list[str]) -> Text:
        if len(self._glyphs) != w:
            self._glyphs = [random.choice("01  ") for _ in range(w)]
        if self._t % 2 == 0:
            self._glyphs = [random.choice("01  ")] + self._glyphs[:-1]
        t = Text()
        for ch in self._glyphs:
            t.append(ch, style=shades[3 if ch in "01" else 0])
        return t

    def _firefly(self, w: int, shades: list[str]) -> Text:
        if len(self._stars) < 2:
            self._stars = [
                [random.uniform(0, w - 1), random.uniform(-1, 1)] for _ in range(max(2, w // 22))
            ]
        cells, sh = [" "] * w, [0] * w
        for s in self._stars:
            s[0] += s[1] * 0.7
            if not (0 <= s[0] < w):
                s[1] = -s[1]
                s[0] = max(0, min(w - 1, s[0]))
            if random.random() < 0.1:
                s[1] += random.uniform(-0.3, 0.3)
            j = int(s[0])
            cells[j], sh[j] = random.choice("✦✺*•"), 4
        t = Text()
        for ch, k in zip(cells, sh, strict=False):
            t.append(ch, style=shades[k])
        return t

    def _fireworks(self, w: int, shades: list[str]) -> Text:
        phase, cyc = self._t % 40, self._t // 40
        c = (cyc * 37) % max(1, w)
        t = Text()
        for i in range(w):
            d = abs(i - c)
            if phase < 3 and d == 0:
                t.append("✺", style=shades[4])
            elif 0 < phase < 18 and d == phase:
                t.append(random.choice("*✦•"), style=shades[max(0, 4 - phase // 5)])
            else:
                t.append(" ")
        return t

    def _zigzag(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            tw = (col + self._t) % 8
            h = tw if tw < 4 else 8 - tw
            t.append(self.BARS[1 + h], style=shades[1 + (h * 3) // 5])
        return t

    def _throb(self, w: int, shades: list[str]) -> Text:
        c = (w / 2) or 1
        b = (math.sin(self._t * 0.2) + 1) / 2
        t = Text()
        for i in range(w):
            v = max(0.0, b - abs(i - c) / c * 0.8)
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _morse(self, w: int, shades: list[str]) -> Text:
        pat = "█ ███ █ █   "
        off = self._t % len(pat)
        t = Text()
        for i in range(w):
            ch = pat[(i + off) % len(pat)]
            t.append(ch, style=shades[3 if ch != " " else 0])
        return t

    def _lava(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = (math.sin(col * 0.10 + self._t * 0.05) + math.sin(col * 0.04 - self._t * 0.03)) / 2
            b = (v + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _worm(self, w: int, shades: list[str]) -> Text:
        seg = 6
        head = self._t % (w + seg)
        t = Text()
        for i in range(w):
            d = head - i
            inside = 0 <= d < seg
            t.append(
                ("●" if d == 0 else "•") if inside else " ",
                style=shades[max(0, 4 - d)] if inside else shades[0],
            )
        return t

    def _aurora(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = (
                math.sin(col * 0.08 + self._t * 0.06)
                + math.sin(col * 0.15 + self._t * 0.03)
                + math.sin(col * 0.03 - self._t * 0.04)
            ) / 3
            b = (v + 1) / 2
            t.append(self.BARS[1 + int(b * (len(self.BARS) - 2))], style=shades[min(4, int(b * 5))])
        return t

    def _crossing(self, w: int, shades: list[str]) -> Text:
        a = (self._t * 2) % (w + 8) - 4
        b = w - ((self._t * 2) % (w + 8) - 4)
        t = Text()
        for i in range(w):
            d = min(abs(i - a), abs(i - b))
            t.append(" " if d > 4 else ("◆" if d == 0 else "─"), style=shades[max(0, 4 - d)])
        return t

    def _glimmer(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for _i in range(w):
            if random.random() < 0.06:
                t.append(random.choice("✦✺*"), style=shades[4])
            else:
                t.append(" ", style=shades[0])
        return t

    def _ladder(self, w: int, shades: list[str]) -> Text:
        n = len(self.BARS)
        t = Text()
        for col in range(w):
            h = (col * 2 + self._t) % (2 * (n - 1))
            h = h if h < n else 2 * (n - 1) - h
            t.append(self.BARS[h], style=shades[min(4, (h * 5) // n)])
        return t

    def _rotor(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for col in range(w):
            v = math.sin((col - self._t) * 0.4) * math.cos(self._t * 0.1)
            b = (v + 1) / 2
            t.append(self.BARS[int(b * (len(self.BARS) - 1))], style=shades[min(4, int(b * 5))])
        return t

    def _parallax(self, w: int, shades: list[str]) -> Text:
        out, sh = [" "] * w, [0] * w
        for speed, ch, s in ((3, "·", 1), (2, "•", 2), (1, "✦", 4)):
            for k in range(0, w, 6):
                pos = (k + self._t * speed) % w
                out[pos], sh[pos] = ch, s
        t = Text()
        for ch, s in zip(out, sh, strict=False):
            t.append(ch, style=shades[s])
        return t

    def _wavefront(self, w: int, shades: list[str]) -> Text:
        pos = self._t % (w + 10) - 5
        n = len(self.BARS)
        t = Text()
        for i in range(w):
            d = abs(i - pos)
            t.append(self.BARS[n - 1 - d] if d < n else " ", style=shades[max(0, 4 - d)])
        return t

    def _symbars(self, w: int, shades: list[str]) -> Text:
        c = w // 2
        t = Text()
        for i in range(w):
            v = (math.sin(abs(i - c) * 0.3 - self._t * 0.2) + 1) / 2
            t.append(self.BARS[int(v * (len(self.BARS) - 1))], style=shades[min(4, int(v * 5))])
        return t

    def _confetti(self, w: int, shades: list[str]) -> Text:
        if len(self._cells) != w or len(self._glyphs) != w:
            self._cells, self._glyphs = [0.0] * w, [" "] * w
        for i in range(w):
            self._cells[i] *= 0.85
        for _ in range(max(1, w // 20)):
            j = random.randrange(w)
            self._cells[j], self._glyphs[j] = 1.0, random.choice("▪▫◆●*✦")
        t = Text()
        for i in range(w):
            v = self._cells[i]
            t.append(" " if v < 0.15 else self._glyphs[i], style=shades[min(4, int(v * 5))])
        return t

    def _noise(self, w: int, shades: list[str]) -> Text:
        t = Text()
        for _i in range(w):
            r = random.random()
            t.append(random.choice(" ░▒▓"), style=shades[min(4, int(r * 5))])
        return t
