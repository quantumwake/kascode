"""Tests for /ai-wellbeing: score parsing, the append-only CSV log, and the
end-to-end assessment with a fake streaming client (CSV redirected to a temp
file). No model/server needed.

Run:  uv run python tests/test_ai_wellbeing.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

import agent.core.ai_wellbeing as aw

# --- parse_scores ----------------------------------------------------------
reply = (
    "The work feels demanding but the goal is clear.\n"
    '{"cognitive_load": 0.7, "stress": 0.3, "clarity": 0.9, "confidence": 0.6, '
    '"frustration": 0.2, "engagement": 0.8, "autonomy": 0.7, "context_pressure": 1.5, '
    '"note": "going well"}'
)
s = aw.parse_scores(reply)
assert s is not None
assert s["cognitive_load"] == 0.7 and s["clarity"] == 0.9
assert s["context_pressure"] == 1.0, s["context_pressure"]  # clamped to [0,1]
assert s["note"] == "going well"
assert aw.parse_scores("no json here") is None
assert aw.parse_scores('{"unrelated": 1}') is None  # no known dimensions
print("parse_scores: OK")

# --- append_csv (append-only, header once) ---------------------------------
tmp = pathlib.Path(tempfile.mkdtemp()) / "ai-wellbeing.csv"
aw.append_csv("/home/me/proj-x", "test-model", "build a thing", s, path=tmp)
aw.append_csv("/home/me/proj-x", "test-model", "build a thing", s, path=tmp)
text = tmp.read_text()
assert text.count("cognitive_load") == 1, "header written exactly once"  # header column name
assert text.count("proj-x") == 2, "two rows appended"
assert "test-model" in text and "going well" in text
print("append_csv: OK")

# --- read_history + chart_lines (text sparklines over time) -----------------
assert aw.read_history(pathlib.Path(tempfile.mkdtemp()) / "nope.csv") == []  # no file
hist = aw.read_history(tmp)
assert len(hist) == 2 and hist[0]["model"] == "test-model"
assert hist[0]["cognitive_load"] == 0.7 and hist[0]["context_pressure"] == 1.0
assert hist[0]["workdir"] == "proj-x" and hist[0]["note"] == "going well"

assert aw.chart_lines([]) == []  # nothing to chart
lines = aw.chart_lines(hist)
text_blob = "\n".join(line for line, _ in lines)
assert "ai-wellbeing · 2 assessments" in lines[0][0]
assert any("cognitive load" in line for line, _ in lines)
assert any(c in text_blob for c in aw._SPARK), "sparkline glyphs present"
# polarity colouring: high burden (cognitive_load 0.70) is red; high-is-good
# clarity (0.90) is green
styles = {line.split("  ")[1].strip(): style for line, style in lines if line.startswith("  ")}
assert styles.get("cognitive load") == "red", styles
assert styles.get("clarity") == "green", styles
assert lines[-1] == ("  note: going well", "dim")
# a row with blank/missing dims -> that dim is skipped, others still chart
sparse = [
    {
        "time": "2026-06-25T00:00:00",
        "workdir": "w",
        "model": "m",
        "note": "",
        "cognitive_load": None,
        "stress": 0.4,
        "clarity": None,
        "confidence": None,
        "frustration": None,
        "engagement": None,
        "autonomy": None,
        "context_pressure": None,
    }
]
sl = aw.chart_lines(sparse)
assert any("stress" in line for line, _ in sl)
assert not any("cognitive load" in line for line, _ in sl)
print("read_history + chart_lines: OK")


# --- assess_wellbeing end-to-end (fake streaming client) -------------------
class _Delta:
    def __init__(self, **kw):
        self.type = "text_delta"
        for k, v in kw.items():
            setattr(self, k, v)


class _Event:
    def __init__(self, delta):
        self.type = "content_block_delta"
        self.delta = delta


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Usage:
    input_tokens = 10
    output_tokens = 20


class _Msg:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _Stream:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        yield _Event(_Delta(text=self.text))

    def get_final_message(self):
        return _Msg(self.text)


class FakeClient:
    class messages:  # noqa: N801
        text = reply

        @classmethod
        def stream(cls, **kw):
            return _Stream(cls.text)


class FakeIO:
    def __init__(self):
        self.notices: list[str] = []
        self.last_decode_tps = 0.0

    def notice(self, t):
        self.notices.append(t)

    def stream_started(self):
        pass

    def stream_finished(self, u):
        pass

    def delta(self, k, t):
        pass


aw.CSV_PATH = pathlib.Path(tempfile.mkdtemp()) / "ai-wellbeing.csv"  # redirect off $HOME
io = FakeIO()
aw.assess_wellbeing(
    FakeClient(), io, [{"role": "user", "content": "build X"}], "test-model", "/w/proj"
)
assert any("cognitive load 0.70" in n for n in io.notices), io.notices
assert any("logged" in n for n in io.notices), io.notices
assert aw.CSV_PATH.exists() and "test-model" in aw.CSV_PATH.read_text()
print("assess_wellbeing end-to-end: OK")

print("all ai-wellbeing tests passed")
