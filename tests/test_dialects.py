"""Dialect detection + tool-call parsing for the main model families.

Locks two things without needing a model or server:
  - detect_dialect() routes templates AND model ids to the right dialect
    (incl. the empty-template / GGUF case where only the id is available);
  - each dialect's StreamParser extracts a real tool call from that family's
    output format, fed CHARACTER BY CHARACTER like a live token stream.

Run:  uv run python tests/test_dialects.py
"""

import os
import sys

sys.path.insert(0, ".")

from server.prompting import (
    DeepSeekDialect,
    GemmaDialect,
    HarmonyDialect,
    HermesDialect,
    KimiDialect,
    LlamaDialect,
    MistralDialect,
    QwenDialect,
    StreamParser,
    detect_dialect,
)
from server.prompting import dialects as dialmod

# ---------------------------------------------------------------------------
# detect_dialect — template markers win, model id is the fallback
# ---------------------------------------------------------------------------

# Template-marker routing (the strongest signal).
assert isinstance(detect_dialect("<function=x>...<|im_start|>"), QwenDialect)  # qwen XML
assert isinstance(detect_dialect("...<tool_call>...<|im_start|>"), HermesDialect)  # qwen3-next/2.5
assert isinstance(detect_dialect("...[TOOL_CALLS]..."), MistralDialect)
assert isinstance(detect_dialect("...<|python_tag|>..."), LlamaDialect)
assert isinstance(detect_dialect("...<｜tool▁calls▁begin｜>..."), DeepSeekDialect)
assert isinstance(detect_dialect("...<|channel>..."), GemmaDialect)
# qwen3-coder ships BOTH markers; XML must win over the generic <tool_call>.
assert isinstance(detect_dialect("<function=x>\n<tool_call>\n<|im_start|>"), QwenDialect)

# Empty-template (GGUF) routing by model id only.
assert isinstance(detect_dialect("", "mlx-community/Qwen3-Coder-Next-4bit"), QwenDialect)
assert isinstance(detect_dialect("", "Qwen/Qwen2.5-32B-Instruct-GGUF"), HermesDialect)
assert isinstance(detect_dialect("", "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF"), LlamaDialect)
assert isinstance(detect_dialect("", "mistralai/Mistral-7B-Instruct-v0.3"), MistralDialect)
assert isinstance(detect_dialect("", "deepseek-ai/DeepSeek-V3"), DeepSeekDialect)
assert isinstance(detect_dialect("", "mlx-community/gemma-4-31b-it-4bit"), GemmaDialect)
assert isinstance(detect_dialect("", "mlx-community/Kimi-K2-Instruct-4bit"), KimiDialect)
assert isinstance(detect_dialect("", "lmstudio-community/gpt-oss-20b-MLX-8bit"), HarmonyDialect)
# Harmony's "<|channel|>" (trailing pipe) must not collide with Gemma's "<|channel>".
assert isinstance(detect_dialect("x<|channel|>analysis<|message|>y"), HarmonyDialect)
assert isinstance(detect_dialect("x<|channel>thought<channel|>y"), GemmaDialect)
# Unknown -> Gemma (unchanged historical default).
assert isinstance(detect_dialect("", "some/unknown-model"), GemmaDialect)
print("detect_dialect: OK")


# ---------------------------------------------------------------------------
# override file — glob on model id, wins over auto-detection
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402
import tempfile  # noqa: E402

with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    _json.dump({"overrides": {"*my-weird-model*": "mistral", "*kimi*": "hermes"}}, f)
    override_path = f.name
_orig = dialmod.OVERRIDES_PATH
dialmod.OVERRIDES_PATH = override_path
try:
    # A model that would auto-detect Gemma is pinned to Mistral.
    assert isinstance(detect_dialect("", "vendor/my-weird-model-7b"), MistralDialect)
    # An override can even REROUTE one that auto-detects correctly (kimi->hermes).
    assert isinstance(detect_dialect("", "mlx-community/Kimi-K2-Instruct-4bit"), HermesDialect)
    # Non-matching ids fall through to normal detection.
    assert isinstance(detect_dialect("", "meta-llama/Llama-3.1-8B"), LlamaDialect)
finally:
    dialmod.OVERRIDES_PATH = _orig
    os.unlink(override_path)
print("override file: OK")


# ---------------------------------------------------------------------------
# parsing — feed each family's real output format char-by-char
# ---------------------------------------------------------------------------

SCHEMAS = {"read_file": {"path": "string"}, "grep": {"pattern": "string", "max": "integer"}}


def parse_one(dialect, output, thinking=False):
    p = StreamParser(dialect, schemas=SCHEMAS, thinking=thinking)
    events = []
    for ch in output:
        events += list(p.feed(ch))
    events += list(p.flush())
    return p.tool_calls, events


# Hermes / ChatML JSON (Qwen3-Next, Qwen2.5, Nous-Hermes, ...)
calls, _ = parse_one(
    HermesDialect(),
    'Sure.\n<tool_call>\n{"name": "read_file", "arguments": {"path": "a.py"}}\n</tool_call>',
)
assert calls == [{"id": calls[0]["id"], "name": "read_file", "input": {"path": "a.py"}}], calls

# Llama 3.x — <|python_tag|>{json with "parameters"}, closed by withheld EOS (flush)
calls, _ = parse_one(
    LlamaDialect(),
    '<|python_tag|>{"name": "grep", "parameters": {"pattern": "TODO", "max": 5}}',
)
assert calls == [
    {"id": calls[0]["id"], "name": "grep", "input": {"pattern": "TODO", "max": 5}}
], calls

# Mistral — [TOOL_CALLS] + JSON array, no close marker (flush parses)
calls, _ = parse_one(
    MistralDialect(),
    '[TOOL_CALLS][{"name": "read_file", "arguments": {"path": "b.py"}}]',
)
assert calls == [{"id": calls[0]["id"], "name": "read_file", "input": {"path": "b.py"}}], calls

# DeepSeek-V3 — sep-delimited name + fenced json
ds = (
    "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>read_file\n"
    '```json\n{"path": "c.py"}\n```<｜tool▁call▁end｜><｜tool▁calls▁end｜>'
)
calls, _ = parse_one(DeepSeekDialect(), ds)
assert calls == [{"id": calls[0]["id"], "name": "read_file", "input": {"path": "c.py"}}], calls

# Kimi-K2 — section-wrapped functions.NAME:idx + argument-begin json
kimi = (
    "<|tool_calls_section_begin|><|tool_call_begin|>functions.read_file:0"
    '<|tool_call_argument_begin|>{"path": "e.py"}<|tool_call_end|>'
    "<|tool_calls_section_end|>"
)
calls, _ = parse_one(KimiDialect(), kimi)
assert calls == [{"id": calls[0]["id"], "name": "read_file", "input": {"path": "e.py"}}], calls

# Harmony (gpt-oss) — analysis channel = thinking, commentary->functions = tool call,
# the <|start|>assistant role re-decl between channels is consumed (no leak).
harmony = (
    "<|channel|>analysis<|message|>Need the file.<|end|>"
    "<|start|>assistant<|channel|>commentary to=functions.read_file <|constrain|>json"
    '<|message|>{"path": "f.py"}<|call|>'
)
calls, events = parse_one(HarmonyDialect(), harmony)
assert "".join(v for k, v in events if k == "thinking") == "Need the file.", events
assert calls == [{"id": calls[0]["id"], "name": "read_file", "input": {"path": "f.py"}}], calls
assert not any(k == "text" and "<|start|>" in v for k, v in events), events  # no marker leak

# Reasoning prefix: a <think> block before the call is parsed as thinking, not text.
calls, events = parse_one(
    HermesDialect(),
    '<think>need the file</think>\n'
    '<tool_call>\n{"name":"read_file","arguments":{"path":"d.py"}}\n</tool_call>',
)
thinking = "".join(v for k, v in events if k == "thinking")
assert thinking == "need the file", thinking
assert calls[0]["name"] == "read_file"

# Malformed call surfaces as visible text rather than vanishing.
_, events = parse_one(HermesDialect(), "<tool_call>\n{not json}\n</tool_call>")
assert any(k == "text" and "not json" in v for k, v in events), events
print("tool parsing: OK")


# ---------------------------------------------------------------------------
# detection against the REAL templates cached on this machine (best-effort:
# skips models that aren't present so CI without the cache still passes)
# ---------------------------------------------------------------------------

import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

HUB = os.path.expanduser("~/.cache/huggingface/hub")
EXPECT = {
    "mlx-community/Qwen3-Coder-Next-4bit": QwenDialect,
    "mlx-community/Qwen3-Next-80B-A3B-Instruct-5bit": HermesDialect,
    "meta-llama/Llama-3.1-8B-Instruct": LlamaDialect,
    "mlx-community/gemma-4-31b-it-4bit": GemmaDialect,
}


def _real_template(repo):
    d = HUB + "/models--" + repo.replace("/", "--")
    snaps = glob.glob(d + "/snapshots/*")
    if not snaps:
        return None
    snap = snaps[0]
    jinja = os.path.join(snap, "chat_template.jinja")
    if os.path.exists(jinja):
        return open(jinja, errors="ignore").read()
    tcfg = os.path.join(snap, "tokenizer_config.json")
    if os.path.exists(tcfg):
        try:
            return json.load(open(tcfg)).get("chat_template") or ""
        except Exception:
            return ""
    return None


checked = 0
for repo, want in EXPECT.items():
    tmpl = _real_template(repo)
    if tmpl is None:
        continue
    got = detect_dialect(tmpl, repo)
    assert isinstance(got, want), f"{repo}: wanted {want.__name__}, got {type(got).__name__}"
    checked += 1
print(f"real-template detection: OK ({checked} cached models checked)")

print("all dialect tests passed")
