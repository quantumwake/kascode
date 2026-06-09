"""Agentic loop driven by the official Anthropic SDK against the local server.

Run:  uv run python -m agent.main [--yolo] [--workdir DIR]

The loop follows the standard manual tool-use pattern: stream the response,
execute any tool_use blocks, send tool_result blocks back, repeat until the
model stops calling tools.
"""

import argparse
import json
import os
import pathlib
from collections import deque
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import threading
import time

import anthropic
import httpx

BASE_URL = os.environ.get("KAS_BASE_URL", "http://127.0.0.1:8765")
MODEL = os.environ.get("KAS_MODEL")  # default: ask the server what it loaded
MAX_TOKENS = int(os.environ.get("KAS_MAX_TOKENS", "16384"))
# Compaction is a decode-speed relief valve, not a context-window necessity —
# KV continuation makes prefill cheap and quantization eases long-context
# decode, so trigger it rarely and high. Too low + a large project = a
# compact→read→compact thrash that never makes progress.
COMPACT_AT = int(os.environ.get("KAS_COMPACT_AT", "120000"))
# Hard floor on turns between compactions — guarantees no tight loop even if
# the work keeps refilling context.
COMPACT_COOLDOWN = int(os.environ.get("KAS_COMPACT_COOLDOWN", "5"))
# Decode-rate trigger: compaction exists to relieve slow decode, so trigger on
# the actual symptom. When smoothed decode tok/s drops below this, mark the
# session compactable (fires at the next safe boundary). 0 disables.
COMPACT_TPS = float(os.environ.get("KAS_COMPACT_TPS", "8.0"))

COMPACT_PROMPT = (
    "Context reset incoming. Write a thorough but compact handoff summary of this "
    "session: the original task; key decisions and constraints; every file created "
    "or modified (path + what it currently contains, outline level); what is DONE "
    "and verified; what remains TODO, in order; any gotchas discovered. Plain text "
    "only. Do not call any tools."
)

TRUNCATION_NOTE = (
    "[automated notice] Your previous response was cut off at the output-token "
    "limit and any incomplete tool call was discarded. Continue the task in "
    "smaller steps: write large files in chunks — write_file for the first "
    "part, then write_file with append=true for each following part."
)


def served_model(base_url: str) -> str | None:
    """Ask the server which model it actually has loaded."""
    return served_info(base_url)[0]


def served_info(base_url: str) -> tuple[str | None, int | None]:
    """Return (model_id, context_length) from the server, or (None, None)."""
    try:
        d = httpx.get(base_url.rstrip("/") + "/v1/models", timeout=5).json()["data"][0]
        return d.get("id"), d.get("context_length")
    except Exception:
        return None, None


class ConsoleIO:
    """Plain-terminal presentation of an agent turn (REPL / one-shot mode)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.hb: "Heartbeat | None" = None
        self._t0 = 0.0
        self._ttft: float | None = None
        self.last_decode_tps: float = 0.0  # decode rate of the most recent turn

    # -- streaming -----------------------------------------------------------
    def stream_started(self) -> None:
        self._t0, self._ttft = time.time(), None
        self.hb = Heartbeat(self.base_url)

    def delta(self, kind: str, text: str) -> None:
        if self._ttft is None:
            self._ttft = time.time() - self._t0
        if self.hb:
            self.hb.tick()
        if kind == "thinking":
            print(f"\033[2m{text}\033[0m", end="", flush=True)
        else:
            print(text, end="", flush=True)

    def stream_finished(self, usage) -> None:
        if self.hb:
            self.hb.stop()
            self.hb = None
        if usage is not None:
            decode_t = max(0.05, (time.time() - self._t0) - (self._ttft or 0))
            self.last_decode_tps = usage.output_tokens / decode_t
            print(
                f"\n\033[2m[{usage.input_tokens} in / {usage.output_tokens} out · "
                f"ttft {self._ttft or 0:.1f}s · {self.last_decode_tps:.1f} tok/s · "
                f"total {time.time() - self._t0:.1f}s]\033[0m"
            )

    # -- tool activity ---------------------------------------------------------
    def tool_call(self, name: str, args: dict) -> None:
        print(f"\n→ {name}({json.dumps(args, ensure_ascii=False)[:200]})")

    def tool_result(self, output: str, is_error: bool) -> None:
        preview = output if len(output) < 300 else output[:300] + "..."
        print(f"  {'✗' if is_error else '✓'} {preview}")

    def notice(self, text: str) -> None:
        print(f"\033[33m{text}\033[0m")

    # -- interaction -----------------------------------------------------------
    def confirm(self, command: str) -> str | None:
        """Ask y/N/a. Returns the answer, or None when no TTY is available."""
        if not sys.stdin.isatty():
            return None
        # Keystrokes typed while the model was generating sit in the stdin
        # buffer and would be consumed as an instant (empty -> decline)
        # answer. Flush them so the question is genuinely asked.
        try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
        return input(f"\n  \033[1mrun `{command}`? [y/N/a=always]\033[0m ").strip().lower()

    def drain_steers(self) -> list[str]:
        return []  # console mode has no mid-run input channel

    def should_abort(self) -> bool:
        return False  # console mode has no mid-run interrupt channel

    def should_pause(self) -> bool:
        return False  # console mode has no pause channel

    def clear_abort(self) -> None:
        pass


class SubagentIO:
    """Routes a subagent's turn through the parent IO, visually demoted.

    Confirmations still go to the user; steering stays with the main thread.
    Full subagent output (thinking/text/tools) is CAPTURED into self.buffer for
    later inspection (the TUI's /subagent drill-in); only compact markers leak
    to the parent's main view so it stays readable.
    """

    def __init__(self, parent, label: str = "", n: int = 0) -> None:
        self.parent = parent
        self.label = label
        self.n = n
        self.status = "running"
        self.buffer: list[str] = []  # captured transcript lines
        self._line = ""

    def _cap(self, text: str) -> None:
        self._line += text
        while "\n" in self._line:
            ln, self._line = self._line.split("\n", 1)
            self.buffer.append(ln)

    def _flush(self) -> None:
        if self._line:
            self.buffer.append(self._line)
            self._line = ""

    @property
    def last_decode_tps(self) -> float:
        return getattr(self.parent, "last_decode_tps", 0.0)

    def stream_started(self):
        self.parent.stream_started()

    def stream_finished(self, usage):
        self._flush()
        self.parent.stream_finished(usage)

    def delta(self, kind: str, text: str):
        self._cap(text)  # full detail → buffer only (keeps the main view clean)

    def tool_call(self, name: str, args: dict):
        self._flush()
        self.buffer.append(f"→ {name}({json.dumps(args, ensure_ascii=False)[:160]})")
        self.parent.tool_call(f"sub[{self.n}]:{name}", args)  # compact line in main view

    def tool_result(self, output: str, is_error: bool):
        self.buffer.append(("✗ " if is_error else "✓ ") + (output[:400]))

    def notice(self, text: str):
        self.buffer.append(text)

    def confirm(self, command: str):
        return self.parent.confirm(command)

    def drain_steers(self) -> list[str]:
        return []  # steering belongs to the main thread

    def should_abort(self) -> bool:
        return self.parent.should_abort()

    def should_pause(self) -> bool:
        return self.parent.should_pause()

    def clear_abort(self) -> None:
        self.parent.clear_abort()


def run_subagent(
    client: anthropic.Anthropic,
    runner: "ToolRunner",
    io,
    model: str,
    max_tokens: int,
    args: dict,
) -> tuple[str, bool]:
    """Execute one subagent task in a fresh context; return its final report."""
    global _subagent_seq
    task = (args or {}).get("task", "").strip()
    if not task:
        return "subagent requires a non-empty 'task'", True
    if args.get("report"):
        task += f"\n\nYour final reply MUST contain: {args['report']}"
    _subagent_seq += 1
    n = _subagent_seq
    thread = f"sub-{n}"  # own KV-cache slot + memo, isolated from main
    label = task[:100].splitlines()[0]
    io.notice(f"[subagent[{n}] ▶ {label}…]")
    sub_io = SubagentIO(io, label=label, n=n)
    if hasattr(io, "subagent_started"):
        io.subagent_started(sub_io)
    messages: list = [{"role": "user", "content": task}]
    try:
        agent_turn(
            client,
            messages,
            runner,
            sub_io,
            model=model,
            max_tokens=max_tokens,
            compact_at=0,  # bounded by rounds instead
            is_subagent=True,
            max_rounds=SUBAGENT_MAX_ROUNDS,
            thread=thread,
        )
    except Exception as exc:
        sub_io.status = "error"
        if hasattr(io, "subagent_finished"):
            io.subagent_finished(sub_io, False)
        return f"subagent failed: {type(exc).__name__}: {exc}", True
    final = ""
    if messages and messages[-1].get("role") == "assistant":
        content = messages[-1]["content"]
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        final = "\n\n".join(
            (b.text if hasattr(b, "text") else b.get("text", ""))
            for b in blocks
            if (getattr(b, "type", None) or b.get("type")) == "text"
        ).strip()
    sub_io.status = "done" if final else "empty"
    if final:
        sub_io.buffer.append(f"[report] {final}")
    io.notice(f"[subagent[{n}] ✔ done]")
    if hasattr(io, "subagent_finished"):
        io.subagent_finished(sub_io, bool(final))
    if not final:
        return "subagent finished without a final report", True
    return _truncate(final), False


class Heartbeat:
    """Shows a live status line whenever the response stream goes quiet.

    Long tool calls are buffered server-side until they close, so the client
    can see nothing for minutes. This thread polls GET /v1/stats and renders
    e.g. `⏳ generating 312 tok @ 10.8 tok/s · 29s` until output resumes.
    """

    QUIET_AFTER = 2.0  # seconds of stream silence before the line appears

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.last_activity = time.time()
        self.showing = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _status_line(self) -> str:
        try:
            s = httpx.get(self.base_url + "/v1/stats", timeout=2).json()
        except Exception:
            return "waiting for server..."
        if not s.get("active"):
            return "waiting..."
        if s.get("phase") == "prefill":
            return f"⏳ prefill {s['processed']}/{s['total']} tok (cache hit {s['cached']}) · {s['elapsed']:.0f}s"
        return f"⏳ generating {s['generated']} tok @ {s['tps']} tok/s · {s['elapsed']:.0f}s"

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            if time.time() - self.last_activity < self.QUIET_AFTER:
                continue
            sys.stdout.write(f"\r\033[2m{self._status_line()}\033[0m\033[K")
            sys.stdout.flush()
            self.showing = True

    def tick(self) -> None:
        """Call before printing real output: clears the status line."""
        self.last_activity = time.time()
        if self.showing:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self.showing = False

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        if self.showing:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self.showing = False
MAX_TOOL_OUTPUT = 8_000

SYSTEM = """\
You are a capable local coding agent running on the user's machine.
Work step by step: inspect before you modify, verify after you change.
Prefer small, targeted tool calls over big speculative ones — they are
dramatically faster and cheaper than large ones.
Editing: work in PATCHES. Never rewrite a whole file to change part of it —
apply a small patch with edit_file (a short unique old_string and its
replacement). For large files, read only the relevant range (read_file with
start_line/end_line) instead of the whole file.
Your output budget per response is limited: build large NEW files in chunks of
at most ~150 lines each (write_file, then write_file with append=true), never
in one giant call.
When the task is complete, summarize what you did in one or two sentences.\
"""

SUBAGENT_HINT = """\
Context budget: your context window is a scarce resource. Delegate bulky,
self-contained subtasks to the subagent tool (it gets a fresh empty context;
only its final report returns to you): analyzing large files or logs,
building an isolated module, running a test-and-fix loop.\
"""

SUBAGENT_TOOL: dict = {
    "name": "subagent",
    "description": (
        "Delegate a self-contained subtask to a fresh agent with its own EMPTY "
        "context window. It has the same file/bash tools and working directory "
        "but sees NOTHING of this conversation — put every needed detail (file "
        "paths, requirements, conventions, constraints) into the task text. "
        "Only its final report returns to you, so use it to keep bulky work out "
        "of your context: analyzing large files or command output, building an "
        "isolated module, running a test-and-fix loop. Prefer it whenever a "
        "subtask would require reading lots of content you don't need to keep."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Complete, self-contained instructions for the subagent",
            },
            "report": {
                "type": "string",
                "description": "What the final report back to you must contain",
            },
        },
        "required": ["task"],
    },
}

SUBAGENT_MAX_ROUNDS = 20
_subagent_seq = 0

# Opt-in network tools (off unless --net / KAS_NET): web search + fetch. kas is
# offline by default — these are the only things that leave the machine.
WEB_TOOLS: list[dict] = [
    {
        "name": "web_search",
        "description": (
            "Search the web and return the top results (title, url, snippet). "
            "Use when the task needs current information or facts not in context, "
            "then web_fetch the most relevant url for full content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Default 5"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a URL and return its main text content (article extraction, "
            "boilerplate stripped). Use after web_search, or on a URL the user gives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The URL to fetch"}},
            "required": ["url"],
        },
    },
]

# Opt-in local retrieval (--rag / KAS_RAG): ranked BM25 recall over the
# codebase, docs, and past session memory (including content compaction
# dropped). Complements grep — use it for "where/how is X" and to recall
# earlier decisions; use grep for exact strings.
RAG_TOOLS: list[dict] = [
    {
        "name": "recall",
        "description": (
            "Search a local index of this project's code + docs AND past session "
            "memory (decisions, summaries, content dropped by compaction), ranked "
            "by relevance. Use for 'where is X handled', 'how does Y work', or to "
            "remember earlier decisions — when you don't know the exact string to "
            "grep for. Returns the most relevant chunks with file:line."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for (natural language ok)"},
                "k": {"type": "integer", "description": "How many results (default 8)"},
            },
            "required": ["query"],
        },
    },
]

TOOLS: list[dict] = [
    {
        "name": "bash",
        "description": (
            "Run a shell command in the working directory (inside a pseudo-terminal) "
            "and return its output. Call this when you need to execute, build, test, "
            "search, or inspect anything not covered by the file tools. Prefer "
            "non-interactive flags (--yes, -y) where available; but if the command "
            "stops and waits for input (a prompt), you'll get the output so far and "
            "the process stays alive — answer it with bash_send_input, keep waiting "
            "with bash_wait, or stop it with bash_kill. Never re-run a command that "
            "is still running."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The command to run"}},
            "required": ["command"],
        },
    },
    {
        "name": "bash_send_input",
        "description": (
            "Send a line of input to the still-running bash command (e.g. answer an "
            "interactive prompt like 'Ok to proceed? (y)'). A newline is appended. "
            "Returns the next chunk of output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Input to send (without trailing newline)"}},
            "required": ["text"],
        },
    },
    {
        "name": "bash_wait",
        "description": (
            "Keep waiting for the still-running bash command and return its next "
            "output. Use when the command is doing slow work (installing, compiling) "
            "rather than waiting for input."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "bash_kill",
        "description": "Terminate the still-running bash command and return any final output.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": (
            "Read a text file. Call this before editing any file. For large files "
            "pass start_line/end_line (1-based, inclusive) to read only the relevant "
            "region — ranged reads are returned with line-number prefixes for "
            "navigation; full reads are returned verbatim (copy old_string for "
            "edit_file from a full or unprefixed read)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "start_line": {"type": "integer", "description": "First line (1-based)"},
                "end_line": {"type": "integer", "description": "Last line (inclusive)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a file with the given content. Set append=true "
            "to append to the end of an existing file instead — use this to build "
            "large files in several smaller calls rather than one huge one (very "
            "large single calls risk hitting your output-token limit and being "
            "discarded)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean", "description": "Append instead of overwrite (default false)"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Apply a patch to a file: replace an exact string. old_string must "
            "appear exactly once; read the file first to copy it verbatim. This is "
            "the preferred way to modify existing files — patch, don't rewrite."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_dir",
        "description": "List the entries of a directory.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Defaults to ."}},
        },
    },
]


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    return text[:MAX_TOOL_OUTPUT] + f"\n... [truncated {len(text) - MAX_TOOL_OUTPUT} chars]"


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[=>()][B0]?")


def _clean_terminal(text: str) -> str:
    """Strip ANSI escapes and emulate carriage-return overwrites (progress bars)."""
    text = _ANSI_RE.sub("", text)
    text = text.replace("\r\n", "\n")  # PTY line endings; lone \r = overwrite
    lines = []
    for line in text.split("\n"):
        if "\r" in line:
            line = line.split("\r")[-1]
        lines.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


class BashSession:
    """A shell command running inside a pseudo-terminal.

    The PTY makes the child believe it has a real terminal, so interactive
    prompts appear in the output instead of deadlocking on a closed pipe; the
    agent can then answer them via send().
    """

    IDLE_TIMEOUT = 10.0  # no output for this long -> probably waiting for input
    WAIT_TIMEOUT = 120.0  # max time one read_until_idle() call blocks

    def __init__(self, command: str, cwd: pathlib.Path) -> None:
        self.command = command
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            env={**os.environ, "TERM": "dumb", "npm_config_yes": "true"},
        )
        os.close(slave)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def read_until_idle(self) -> tuple[str, str]:
        """Collect output until the process exits, goes idle, or times out.

        Returns (output, status) with status in {"exited", "waiting", "timeout"}.
        """
        start = last_data = time.time()
        chunks: list[bytes] = []
        while True:
            ready, _, _ = select.select([self.master], [], [], 0.25)
            if ready:
                try:
                    data = os.read(self.master, 65536)
                except OSError:  # EIO: child side closed
                    data = b""
                if not data:
                    self.proc.wait()
                    return self._decode(chunks), "exited"
                chunks.append(data)
                last_data = time.time()
            elif not self.alive():
                return self._decode(chunks), "exited"
            elif time.time() - last_data > self.IDLE_TIMEOUT:
                return self._decode(chunks), "waiting"
            if time.time() - start > self.WAIT_TIMEOUT:
                return self._decode(chunks), "timeout"

    @staticmethod
    def _decode(chunks: list[bytes]) -> str:
        return _clean_terminal(b"".join(chunks).decode(errors="replace"))

    def send(self, text: str) -> None:
        os.write(self.master, (text + "\n").encode())

    def kill(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait()
        try:
            os.close(self.master)
        except OSError:
            pass

    def close(self) -> None:
        try:
            os.close(self.master)
        except OSError:
            pass


WORKSPACE_GITIGNORE = ".agent/\nnode_modules/\n.venv/\n__pycache__/\n.DS_Store\n"


class ToolRunner:
    def __init__(
        self,
        workdir: pathlib.Path,
        yolo: bool,
        io: "ConsoleIO | None" = None,
        checkpoint: bool = False,
        net: bool = False,
        rag: bool = False,
        context_limit: int | None = None,
    ) -> None:
        self.workdir = workdir
        self.yolo = yolo
        self.io = io or ConsoleIO(BASE_URL)
        self.net = net  # web_search / web_fetch available only when True
        self.rag = rag  # recall tool available only when True
        self._rag_index = None
        self.context_limit = context_limit  # model's native context window (overflow safety)
        self.tps_window: deque = deque(maxlen=4)  # recent decode tok/s, for the trigger
        self.session: BashSession | None = None
        self.force_checkpoint = checkpoint  # commit even into a pre-existing repo
        self.mutated = False  # any tool may have changed files this turn
        self._repo: bool | None = None  # lazily decided
        # context size right after the last compaction; auto-compaction
        # triggers on GROWTH beyond this, not on an absolute threshold —
        # otherwise post-compaction re-reads immediately re-trigger it
        self.compact_floor = 0
        self.compact_cooldown = 0  # turns remaining before compaction may fire again

    # -- workspace checkpointing ----------------------------------------------

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.workdir, capture_output=True, text=True, timeout=60
        )

    def _repo_ready(self) -> bool:
        """Decide once whether this workdir gets per-turn commits.

        Yes when: we already initialized it (marker), the dir is not in any
        repo (init one), or it sits inside a repo but is gitignored by it —
        the 'outputs as separate nested repos' case. A user's existing repo is
        never auto-committed to unless --checkpoint was passed.
        """
        if self._repo is not None:
            return self._repo
        marker = self.workdir / ".agent" / "workspace-repo"
        if marker.exists():
            self._repo = True
            return True
        inside = self._git("rev-parse", "--is-inside-work-tree").returncode == 0
        nested_ok = False
        if inside:
            has_own_git = (self.workdir / ".git").exists()
            ignored = self._git("check-ignore", "-q", str(self.workdir)).returncode == 0
            if has_own_git:
                self._repo = True  # already its own repo
                return True
            if not ignored and not self.force_checkpoint:
                self._repo = False  # someone else's repo — hands off
                return False
            nested_ok = ignored
        if not inside or nested_ok:
            self._git("init", "-q", "-b", "main")
            gi = self.workdir / ".gitignore"
            if not gi.exists():
                gi.write_text(WORKSPACE_GITIGNORE)
            self._git("add", "-A")
            self._git("commit", "-q", "-m", "baseline (before agent changes)")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("initialized by local-agent\n")
            self.io.notice(f"[workspace repo initialized: {self.workdir}]")
        self._repo = True
        return True

    def checkpoint(self, label: str) -> str | None:
        """Commit this turn's changes; returns the short sha or None."""
        if not self.mutated:
            return None
        self.mutated = False
        try:
            if not self._repo_ready():
                return None
            self._git("add", "-A")
            if self._git("diff", "--cached", "--quiet").returncode == 0:
                return None  # nothing actually changed
            self._git("commit", "-q", "-m", f"agent: {label}")
            return self._git("rev-parse", "--short", "HEAD").stdout.strip() or None
        except Exception:
            return None  # checkpointing must never break the loop

    def _resolve(self, path: str) -> pathlib.Path:
        p = pathlib.Path(path)
        return p if p.is_absolute() else self.workdir / p

    MUTATING_TOOLS = ("write_file", "edit_file", "bash", "bash_send_input")

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (output, is_error)."""
        try:
            handler = getattr(self, f"tool_{name}", None)
            if handler is None:
                return f"unknown tool: {name}", True
            if name in self.MUTATING_TOOLS:
                # Ensure the workspace repo (and its pre-agent baseline commit)
                # exists BEFORE the first change lands.
                try:
                    self._repo_ready()
                except Exception:
                    pass
            output, is_error = handler(**args)
            if not is_error and name in self.MUTATING_TOOLS:
                self.mutated = True  # may have changed the workspace
            return output, is_error
        except Exception as exc:  # surface errors to the model, don't crash
            return f"{type(exc).__name__}: {exc}", True

    def _session_report(self) -> tuple[str, bool]:
        assert self.session is not None
        out, status = self.session.read_until_idle()
        if status == "exited":
            code = self.session.proc.returncode
            self.session.close()
            self.session = None
            if code:
                out += f"\n[exit code {code}]"
            return _truncate(out.strip() or "(no output)"), bool(code)
        hint = (
            "no output for 10s — it is probably waiting for input"
            if status == "waiting"
            else "still producing output after 120s"
        )
        return (
            _truncate(out)
            + f"\n[process still running: {hint}. Use bash_send_input to answer a "
            "prompt, bash_wait to keep waiting, or bash_kill to stop it.]",
            False,
        )

    def tool_bash(self, command: str) -> tuple[str, bool]:
        if self.session is not None and self.session.alive():
            return (
                f"a previous command is still running (`{self.session.command}`). "
                "Interact with it via bash_send_input / bash_wait, or stop it with "
                "bash_kill before starting a new one.",
                True,
            )
        if not self.yolo:
            answer = self.io.confirm(command)
            if answer is None:
                return (
                    "cannot ask the user for confirmation (stdin is not a TTY) — "
                    "re-run the agent with --yolo to auto-approve commands",
                    True,
                )
            if answer in ("a", "always"):
                self.yolo = True
                self.io.notice("yolo enabled for this session (/yolo to turn off)")
            elif answer not in ("y", "yes"):
                return "user declined to run this command", True
        self.session = BashSession(command, self.workdir)
        return self._session_report()

    def tool_bash_send_input(self, text: str) -> tuple[str, bool]:
        if self.session is None or not self.session.alive():
            return "no command is currently running", True
        self.session.send(text)
        return self._session_report()

    def tool_bash_wait(self) -> tuple[str, bool]:
        if self.session is None or not self.session.alive():
            return "no command is currently running", True
        return self._session_report()

    def tool_bash_kill(self) -> tuple[str, bool]:
        if self.session is None:
            return "no command is currently running", True
        self.session.kill()
        self.session = None
        return "process terminated", False

    def tool_read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> tuple[str, bool]:
        text = self._resolve(path).read_text()
        if start_line is None and end_line is None:
            return _truncate(text), False
        lines = text.splitlines()
        lo = max(1, start_line or 1)
        hi = min(len(lines), end_line or len(lines))
        if lo > len(lines):
            return f"start_line {lo} is past end of file ({len(lines)} lines)", True
        body = "\n".join(f"{i:>5}: {lines[i - 1]}" for i in range(lo, hi + 1))
        return _truncate(f"[lines {lo}-{hi} of {len(lines)}]\n{body}"), False

    def tool_write_file(self, path: str, content: str, append: bool = False) -> tuple[str, bool]:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a" if append else "w") as f:
            f.write(content)
        verb = "appended" if append else "wrote"
        return f"{verb} {len(content)} chars to {p}", False

    def tool_edit_file(self, path: str, old_string: str, new_string: str) -> tuple[str, bool]:
        p = self._resolve(path)
        text = p.read_text()
        count = text.count(old_string)
        if count == 0:
            return "old_string not found in file", True
        if count > 1:
            return f"old_string appears {count} times; it must be unique", True
        p.write_text(text.replace(old_string, new_string, 1))
        return f"edited {p}", False

    def tool_recall(self, query: str, k: int = 8) -> tuple[str, bool]:
        from agent.rag import RagIndex

        if self._rag_index is None:
            (self.workdir / ".agent").mkdir(parents=True, exist_ok=True)
            self._rag_index = RagIndex(self.workdir / ".agent" / "rag.db")
        try:
            self._rag_index.refresh(self.workdir)  # incremental: unchanged files skipped
        except Exception as exc:
            return f"recall index refresh failed: {type(exc).__name__}: {exc}", True
        hits = self._rag_index.search(query, k=max(1, min(int(k or 8), 20)))
        if not hits:
            return f"no matches for {query!r} (try grep for exact strings)", False
        out = []
        for i, h in enumerate(hits, 1):
            snippet = h["body"] if len(h["body"]) < 600 else h["body"][:600] + "…"
            out.append(f"{i}. {h['path']}:{h['lines']} [{h['source']}]\n{snippet}")
        return _truncate("\n\n".join(out)), False

    def tool_web_search(self, query: str, max_results: int = 5) -> tuple[str, bool]:
        try:
            from ddgs import DDGS
        except ImportError:
            return "web search unavailable (pip install ddgs)", True
        n = max(1, min(int(max_results or 5), 10))
        results = list(DDGS().text(query, max_results=n))
        if not results:
            return f"no results for {query!r}", False
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', '')}\n   {r.get('href', '')}\n   {r.get('body', '')}")
        return _truncate("\n\n".join(lines)), False

    def tool_web_fetch(self, url: str) -> tuple[str, bool]:
        try:
            import trafilatura
        except ImportError:
            return "web fetch unavailable (pip install trafilatura)", True
        try:
            resp = httpx.get(
                url, follow_redirects=True, timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (kas agent)"},
            )
            resp.raise_for_status()
        except Exception as exc:
            return f"fetch failed: {type(exc).__name__}: {exc}", True
        text = trafilatura.extract(resp.text, include_links=False) or ""
        if not text.strip():
            # fall back to a crude tag strip if extraction found no article body
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return f"no readable content at {url}", True
        return _truncate(f"[{url}]\n\n{text}"), False

    def tool_list_dir(self, path: str = ".") -> tuple[str, bool]:
        entries = sorted(self._resolve(path).iterdir())
        return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries) or "(empty)", False


def _turn_label(messages: list) -> str:
    """Latest user text (task or steer), for checkpoint commit messages."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg["content"]
        if isinstance(content, str):
            return content[:60]
        for b in reversed(content):
            text = b.get("text") if isinstance(b, dict) else None
            if text:
                return text[:60]
    return "agent changes"


def _jsonable(obj):
    """Recursively convert SDK content blocks to plain JSON-able structures."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    return obj


class SessionStore:
    """Per-session archive under <workdir>/.agent/sessions/<session-id>/.

    Stores the running transcript (autosaved after every turn, resumable via
    --resume) and compaction events (the full original transcript next to the
    summary that replaced it, so no context is ever silently lost).
    """

    TRANSCRIPT = "transcript.json"

    def __init__(self, workdir: pathlib.Path, session_id: str | None = None) -> None:
        self.root = pathlib.Path(workdir) / ".agent" / "sessions"
        self.id = session_id or time.strftime("%Y%m%d-%H%M%S")
        self.dir = self.root / self.id
        self.compactions = (
            len(list(self.dir.glob("compaction-*.json"))) if self.dir.exists() else 0
        )

    def save_transcript(
        self, messages: list, model: str | None = None, paused: bool = False
    ) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        first = next((m for m in messages if m.get("role") == "user"), None)
        title = ""
        if first is not None:
            content = first["content"]
            title = (content if isinstance(content, str) else json.dumps(_jsonable(content)))[:80]
        with open(self.dir / self.TRANSCRIPT, "w") as f:
            json.dump(
                {
                    "id": self.id,
                    "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model": model,
                    "title": title,
                    "paused": paused,
                    "messages": _jsonable(messages),
                },
                f,
                indent=1,
                ensure_ascii=False,
                default=str,
            )

    @staticmethod
    def should_continue(messages: list, paused: bool) -> bool:
        """Was the session mid-task when saved? If so, resume re-enters the loop
        instead of waiting for new input."""
        if paused:
            return True
        if not messages:
            return False
        last = messages[-1]
        if last.get("role") == "user":
            return True  # the model owed a response (mid tool-loop)
        # assistant turn with unfulfilled tool_use also counts as mid-loop
        content = last.get("content")
        if last.get("role") == "assistant" and isinstance(content, list):
            return any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        return False

    @classmethod
    def sessions(cls, workdir: pathlib.Path) -> list[dict]:
        """Resumable sessions for this workdir, oldest first."""
        out = []
        for d in sorted((pathlib.Path(workdir) / ".agent" / "sessions").glob("*/")):
            path = d / cls.TRANSCRIPT
            if not path.exists():
                continue
            try:
                data = json.load(open(path))
            except (OSError, json.JSONDecodeError):
                continue
            out.append(
                {
                    "id": d.name,
                    "updated": data.get("updated", ""),
                    "messages": len(data.get("messages", [])),
                    "title": data.get("title", ""),
                }
            )
        return out

    @classmethod
    def resume(cls, workdir: pathlib.Path, session_id: str | None = None):
        """Return (store, messages) for a session; latest when id is None."""
        if session_id is None:
            existing = cls.sessions(workdir)
            if not existing:
                return None, None
            session_id = existing[-1]["id"]
        path = pathlib.Path(workdir) / ".agent" / "sessions" / session_id / cls.TRANSCRIPT
        if not path.exists():
            return None, None
        data = json.load(open(path))
        store = cls(workdir, session_id=session_id)
        store.was_paused = bool(data.get("paused"))  # type: ignore[attr-defined]
        return store, data["messages"]

    def save_compaction(self, original_messages: list, summary: str, meta: dict) -> pathlib.Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.compactions += 1
        path = self.dir / f"compaction-{self.compactions:02d}.json"
        with open(path, "w") as f:
            json.dump(
                {
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    **meta,
                    "summary": summary,
                    "original_messages": _jsonable(original_messages),
                },
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        return path


def compact_messages(
    client: anthropic.Anthropic,
    messages: list,
    io: ConsoleIO,
    model: str,
    tokens_now: int | None = None,
    store: SessionStore | None = None,
    thread: str = "main",
    max_tokens: int = 16384,
    tools: list | None = None,
) -> None:
    """Replace the transcript with a model-written handoff summary.

    Long sessions decode slower (full-attention layers read the whole KV cache
    per token) and most of the transcript is file content already on disk.

    The summary request reuses the thread's existing KV cache: it sends the
    SAME system + tools as normal turns (so the continuation memo key matches)
    and merges the compaction prompt into the trailing user turn (so the
    request stays the +2-message shape continuation requires). That makes it a
    near-instant cache hit instead of a full re-prefill of the transcript.
    """
    io.notice(
        f"[compacting{f' {tokens_now} tokens' if tokens_now else ''} — "
        "summarizing, then context resets and decode speeds back up…]"
    )

    # Merge the compaction prompt into the last user turn (keeps continuation
    # shape); fall back to a new user message only if the last turn isn't user.
    req_messages = list(messages)
    if req_messages and req_messages[-1].get("role") == "user":
        content = req_messages[-1]["content"]
        blocks = list(content) if isinstance(content, list) else [{"type": "text", "text": content}]
        req_messages[-1] = {"role": "user", "content": blocks + [{"type": "text", "text": COMPACT_PROMPT}]}
    else:
        req_messages = req_messages + [{"role": "user", "content": COMPACT_PROMPT}]

    io.stream_started()
    response = None
    announced = False
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,  # room for thinking AND the summary, or it cuts off mid-thought
            system=f"{SYSTEM}\n\n{SUBAGENT_HINT}",  # must match normal turns for the cache key
            tools=tools if tools is not None else TOOLS + [SUBAGENT_TOOL],
            thinking={"type": "adaptive"},
            messages=req_messages,
            extra_headers={"x-agent-thread": thread},
        ) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if not announced:
                    io.notice("[step 2/2: writing the handoff summary…]")
                    announced = True
                # render the whole summary (and its reasoning) dimmed
                if event.delta.type == "thinking_delta":
                    io.delta("thinking", event.delta.thinking)
                elif event.delta.type == "text_delta":
                    io.delta("thinking", event.delta.text)
            response = stream.get_final_message()
    finally:
        io.stream_finished(response.usage if response else None)
    summary = "\n".join(b.text for b in response.content if b.type == "text")
    if store is not None:
        path = store.save_compaction(
            messages,
            summary,
            {"model": model, "input_tokens_at_compaction": tokens_now},
        )
        io.notice(f"[original context archived: {path}]")
    messages[:] = [
        {
            "role": "user",
            "content": (
                "[The session context was compacted. Handoff summary of everything "
                f"so far:]\n\n{summary}\n\n[Continue the task from where the summary "
                "leaves off. Files mentioned above are on disk — do NOT re-read whole "
                "files; read only the specific line ranges you need (read_file with "
                "start_line/end_line), and patch with edit_file.]"
            ),
        }
    ]
    io.notice(
        f"[context compacted{f': {tokens_now} tokens → summary' if tokens_now else ''} — "
        "the next turn re-reads only the summary, then stays fast]"
    )


def _should_compact(runner: "ToolRunner", input_tokens: int, compact_at: int):
    """Decide whether to compact, by reason. Returns (do, reason).

    Priority: (1) context-overflow safety — must compact, overrides cooldown;
    (2) decode-rate — the real symptom compaction relieves; (3) optional
    absolute token cap. (2) and (3) respect the cooldown.
    """
    if runner.context_limit and input_tokens > int(0.85 * runner.context_limit):
        return True, f"nearing context limit ({input_tokens}/{runner.context_limit})"
    if runner.compact_cooldown > 0:
        return False, ""
    w = runner.tps_window
    if COMPACT_TPS and len(w) >= 2:
        smoothed = sum(w) / len(w)
        if smoothed < COMPACT_TPS:
            return True, f"decode slowed to {smoothed:.1f} tok/s"
    if compact_at and (input_tokens - runner.compact_floor) > compact_at:
        return True, f"size {input_tokens} tok"
    return False, ""


def agent_turn(
    client: anthropic.Anthropic,
    messages: list,
    runner: ToolRunner,
    io: ConsoleIO,
    model: str | None = None,
    max_tokens: int | None = None,
    compact_at: int | None = None,
    store: SessionStore | None = None,
    is_subagent: bool = False,
    max_rounds: int | None = None,
    thread: str = "main",
) -> None:
    """One user turn: loop until the model stops calling tools.

    Steering messages submitted mid-run (io.drain_steers) are injected as user
    text alongside the next tool results, so the model sees them at the next
    boundary without interrupting generation.

    model/max_tokens must be passed explicitly by callers from other modules:
    when running via `python -m agent.main`, this file exists twice (__main__
    and agent.main) and the module-global fallbacks are only set on __main__.
    """
    model = model or MODEL
    max_tokens = max_tokens or MAX_TOKENS
    compact_at = COMPACT_AT if compact_at is None else compact_at
    if model is None:
        raise ValueError("no model resolved — is the server running?")
    tools = list(TOOLS)
    if not is_subagent:
        tools.append(SUBAGENT_TOOL)
    if runner.rag:
        tools += RAG_TOOLS  # opt-in; stable per session so the cache key holds
    if runner.net:
        tools += WEB_TOOLS
    truncations = 0
    rounds = 0
    reconnects = 0  # consecutive dropped-connection retries for the current turn
    while True:
        rounds += 1
        if max_rounds is not None and rounds > max_rounds:
            io.notice(f"[round limit {max_rounds} reached — wrapping up]")
            return
        io.clear_abort()
        io.stream_started()
        response = None
        aborted = False
        partial: list[dict] = []  # accumulated deltas, kept if interrupted
        try:
            # max_retries=0: own the retry here so a dropped connection is
            # surfaced (the SDK's built-in retry is silent).
            with client.with_options(max_retries=0).messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=SYSTEM if is_subagent else f"{SYSTEM}\n\n{SUBAGENT_HINT}",
                tools=tools,
                thinking={"type": "adaptive"},
                messages=messages,
                extra_headers={"x-agent-thread": thread},
            ) as stream:
                for event in stream:
                    if io.should_abort():
                        aborted = True
                        break  # closing the stream cancels server-side generation
                    if event.type == "content_block_delta":
                        kind = field = None
                        if event.delta.type == "thinking_delta":
                            kind, field, piece = "thinking", "thinking", event.delta.thinking
                        elif event.delta.type == "text_delta":
                            kind, field, piece = "text", "text", event.delta.text
                        if kind is not None:
                            io.delta(kind, piece)
                            if partial and partial[-1]["type"] == kind:
                                partial[-1][field] += piece
                            else:
                                block = {"type": kind, field: piece}
                                if kind == "thinking":
                                    block["signature"] = ""
                                partial.append(block)
                if not aborted:
                    response = stream.get_final_message()
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            io.stream_finished(None)
            if partial or reconnects >= 3:
                raise  # content already shown, or out of retries — give up
            reconnects += 1
            io.notice(f"[connection dropped ({type(exc).__name__}) — reconnecting {reconnects}/3…]")
            rounds -= 1  # a reconnect isn't a real round
            time.sleep(min(2 * reconnects, 6))
            continue
        except BaseException:
            io.stream_finished(None)  # always stop the heartbeat
            raise
        else:
            reconnects = 0  # this turn's stream completed cleanly
            io.stream_finished(response.usage if response else None)

        if aborted:
            kept = [
                b for b in partial if (b.get("text") or b.get("thinking", "")).strip()
            ]
            if kept:
                messages.append({"role": "assistant", "content": kept})
            # Pause: stop cleanly, keep partial, let the caller save + exit.
            # Resume re-enters the loop and continues the task.
            if io.should_pause():
                io.notice("[paused — partial output kept; resume to continue]")
                return
            io.notice("[response interrupted — partial output kept]")
            steers = [
                {"type": "text", "text": f"[user steering message] {s}"}
                for s in io.drain_steers()
            ]
            if steers:
                io.notice(f"[injecting {len(steers)} steering message(s)]")
                messages.append({"role": "user", "content": steers})
                continue
            return

        messages.append({"role": "assistant", "content": response.content})

        truncated = response.stop_reason == "max_tokens"
        if truncated:
            truncations += 1
            io.notice(
                f"[response hit the {max_tokens}-token output limit; recovery {truncations}/3]"
            )

        # Execute any COMPLETED tool calls (present even when a later call in
        # the same response was truncated).
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            io.tool_call(block.name, block.input)
            if block.name == "subagent":
                if is_subagent:
                    output, is_error = "subagents cannot spawn subagents", True
                else:
                    output, is_error = run_subagent(
                        client, runner, io, model, max_tokens, block.input
                    )
            else:
                output, is_error = runner.run(block.name, block.input)
            io.tool_result(output, is_error)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": is_error,
                }
            )

        if results:
            sha = runner.checkpoint(_turn_label(messages))
            if sha:
                io.notice(f"[checkpoint {sha}]")

        steers = [
            {"type": "text", "text": f"[user steering message] {s}"} for s in io.drain_steers()
        ]
        if steers:
            io.notice(f"[injecting {len(steers)} steering message(s)]")

        if truncated and truncations >= 3:
            io.notice("[giving up after 3 truncated responses — try a smaller task]")
            if results or steers:
                messages.append({"role": "user", "content": results + steers})
            return
        if truncated:
            content: list = results + steers + [{"type": "text", "text": TRUNCATION_NOTE}]
            messages.append({"role": "user", "content": content})
            continue
        if not results and not steers:
            return
        messages.append({"role": "user", "content": results + steers})

        # Compaction (decode-speed relief). Trigger primarily on the real
        # symptom — decode tok/s falling below COMPACT_TPS over a rolling
        # window — with a context-overflow safety on top. A hard COOLDOWN
        # plus clearing the window after compaction makes a compact→read→
        # compact thrash structurally impossible.
        runner.tps_window.append(io.last_decode_tps)
        do_compact, reason = _should_compact(runner, response.usage.input_tokens, compact_at)
        if do_compact:
            io.notice(f"[compaction trigger: {reason}]")
            compact_messages(
                client, messages, io, model, response.usage.input_tokens,
                store=store, thread=thread, max_tokens=max_tokens, tools=tools,
            )
            summary_chars = len(messages[0]["content"]) if messages else 0
            runner.compact_floor = summary_chars // 4 + 1000  # ~tokens + system/tools
            runner.compact_cooldown = COMPACT_COOLDOWN
            runner.tps_window.clear()  # post-compaction decode is fast; don't re-trigger on stale lows
        elif runner.compact_cooldown > 0:
            runner.compact_cooldown -= 1


def serve_main(argv: list[str]) -> None:
    """`kas serve` — run the inference server. Daemonizes by default."""
    import signal
    import subprocess

    ap = argparse.ArgumentParser(prog="kas serve")
    ap.add_argument("--port", type=int, default=int(os.environ.get("KAS_PORT", "8765")))
    ap.add_argument("--model", default=None, help="model repo to load")
    ap.add_argument("--daemon", action=argparse.BooleanOptionalAction, default=True,
                    help="run in background (default; --no-daemon to run in foreground)")
    ap.add_argument("--stop", action="store_true", help="stop the running server")
    ap.add_argument("--status", action="store_true", help="show server status")
    ap.add_argument("--logs", action="store_true", help="tail the server log")
    a = ap.parse_args(argv)

    state = pathlib.Path.home() / ".kas"
    state.mkdir(exist_ok=True)
    pidf, logf = state / "server.pid", state / "server.log"
    base = f"http://127.0.0.1:{a.port}"

    def pid() -> int | None:
        try:
            p = int(pidf.read_text())
            os.kill(p, 0)
            return p
        except (OSError, ValueError):
            return None

    if a.stop:
        p = pid()
        if p:
            os.killpg(os.getpgid(p), signal.SIGTERM) if hasattr(os, "getpgid") else os.kill(p, signal.SIGTERM)
            pidf.unlink(missing_ok=True)
            print(f"stopped (pid {p})")
        else:
            print("not running")
        return
    if a.status:
        p = pid()
        # Probe the port too — a server started another way (make start, bare
        # kas-server) won't be in our pidfile but is still serving.
        try:
            m = httpx.get(base + "/v1/models", timeout=2).json()["data"][0]["id"]
            up = True
        except Exception:
            m, up = None, False
        if p and up:
            print(f"running (pid {p}) · {m} · {base}")
        elif up:
            print(f"running (not daemon-managed) · {m} · {base}")
        elif p:
            print(f"process {p} alive but not responding on {base} (still loading?)")
        else:
            print("not running")
        return
    if a.logs:
        subprocess.run(["tail", "-f", str(logf)])
        return

    if a.model:
        os.environ["KAS_MODEL"] = a.model

    if not a.daemon:  # foreground: become the server (the kas-server process)
        from server import cli as server_cli
        sys.argv = ["kas-server", "--port", str(a.port)]
        server_cli.main()
        return

    if pid():
        print(f"already running (pid {pid()}) — `kas serve --stop` first")
        return

    # daemonize: spawn the SEPARATE kas-server binary, detached; wait for ready.
    # (Spawning a distinct process, not re-entering kas, avoids the pidfile
    # self-detection footgun.)
    cmd = [sys.executable, "-m", "server.cli", "--port", str(a.port)]
    log = open(logf, "a")
    proc = subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True, env={**os.environ})
    pidf.write_text(str(proc.pid))
    print(f"starting kas server (pid {proc.pid}) on {base} — loading model…")
    for _ in range(180):
        try:
            httpx.get(base + "/v1/models", timeout=1)
            print(f"ready: {base}  (logs: kas serve --logs · stop: kas serve --stop)")
            return
        except Exception:
            if proc.poll() is not None:
                print(f"server exited early — see {logf}")
                return
            time.sleep(2)
    print(f"server slow to start — check {logf}")


def main() -> None:
    global MODEL, BASE_URL, MAX_TOKENS, COMPACT_AT

    # subcommands: `kas serve ...` and `kas agent ...` (bare `kas` = agent)
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve_main(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "agent":
        del sys.argv[1]  # strip so the agent parser sees the rest

    ap = argparse.ArgumentParser(prog="kas", description="kas — your local agent")
    ap.add_argument("--yolo", action="store_true", help="run bash commands without confirmation")
    ap.add_argument("--workdir", default=".", help="working directory for tools")
    ap.add_argument("--model", default=MODEL, help="model id (default: whatever the server loaded)")
    ap.add_argument("--base-url", default=BASE_URL, help="inference server URL")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS, help="output token cap per response")
    ap.add_argument("--compact-at", type=int, default=COMPACT_AT, help="auto-compact context past this many input tokens (0 disables)")
    ap.add_argument("--plain", action="store_true", help="plain REPL instead of the TUI")
    ap.add_argument("--checkpoint", action="store_true",
                    help="commit per-turn checkpoints even when workdir is a pre-existing repo")
    ap.add_argument("--net", action="store_true", default=os.environ.get("KAS_NET") == "1",
                    help="enable web_search/web_fetch (off by default — kas is offline)")
    ap.add_argument("--rag", action=argparse.BooleanOptionalAction,
                    default=os.environ.get("KAS_RAG", "1") != "0",
                    help="recall tool — local BM25 over code/docs/memory (on by default; --no-rag to disable)")
    ap.add_argument("--resume", nargs="?", const="__latest__", metavar="SESSION_ID",
                    help="resume a saved session (latest for this workdir if no id given)")
    ap.add_argument("--sessions", action="store_true", help="list resumable sessions and exit")
    ap.add_argument("task", nargs="*", help="optional one-shot task; omit for interactive mode")
    args = ap.parse_args()
    MAX_TOKENS = args.max_tokens
    COMPACT_AT = args.compact_at
    BASE_URL = args.base_url
    served, context_limit = served_info(BASE_URL)
    MODEL = args.model or served
    if MODEL is None:
        sys.exit(f"server at {BASE_URL} is not reachable — start it with: make start")

    workdir = pathlib.Path(args.workdir).resolve()

    if args.sessions:
        sessions = SessionStore.sessions(workdir)
        if not sessions:
            print(f"no saved sessions under {workdir}/.agent/sessions/")
            return
        for s in sessions:
            print(f"{s['id']}  {s['updated']}  {s['messages']:>3} msgs  {s['title']}")
        print(f"\nresume with: python -m agent.main --resume <SESSION_ID> --workdir {workdir}")
        return

    # Resilient transport: the server pings every few seconds during long
    # prefills so the stream never goes silent (httpx read timeout is per-gap,
    # not total), and max_retries reconnects on a dropped connection.
    client = anthropic.Anthropic(
        base_url=BASE_URL,
        api_key="local",
        max_retries=3,
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
    )

    messages: list = []
    store = None
    if args.resume:
        wanted = None if args.resume == "__latest__" else args.resume
        store, messages = SessionStore.resume(workdir, wanted)
        if store is None:
            sys.exit(f"no resumable session{f' {wanted!r}' if wanted else ''} under {workdir}/.agent/sessions/")
        print(f"resumed session {store.id} ({len(messages)} messages)")
    if store is None:
        store = SessionStore(workdir)

    from scripts.banner import print_console

    if args.task:  # one-shot
        io = ConsoleIO(BASE_URL)
        runner = ToolRunner(workdir, yolo=args.yolo, io=io, checkpoint=args.checkpoint, net=args.net, rag=args.rag, context_limit=context_limit)
        print_console(model=MODEL, extra=f"workdir {workdir} · yolo {args.yolo}")
        messages.append({"role": "user", "content": " ".join(args.task)})
        try:
            agent_turn(client, messages, runner, io, store=store)
        finally:
            store.save_transcript(messages, MODEL)
        return

    if not args.plain and sys.stdin.isatty():  # interactive: TUI with steering
        from agent.tui import AgentApp

        AgentApp(
            client=client,
            model=MODEL,
            base_url=BASE_URL,
            workdir=workdir,
            yolo=args.yolo,
            max_tokens=MAX_TOKENS,
            compact_at=COMPACT_AT,
            store=store,
            messages=messages,
            checkpoint=args.checkpoint,
            net=args.net,
            rag=args.rag,
            context_limit=context_limit,
        ).run()
        return

    # plain REPL fallback
    io = ConsoleIO(BASE_URL)
    runner = ToolRunner(workdir, yolo=args.yolo, io=io, checkpoint=args.checkpoint, net=args.net, rag=args.rag, context_limit=context_limit)
    print_console(model=MODEL, extra=f"workdir {workdir} · yolo {args.yolo}")
    print("REPL commands: /yolo  /status  exit · at a confirm prompt: y / N / a=always")
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user or user in ("exit", "quit"):
            return
        if user.startswith("/"):
            if user == "/yolo":
                runner.yolo = not runner.yolo
                print(f"yolo {'ON — commands run without confirmation' if runner.yolo else 'OFF — commands need approval'}")
            elif user == "/status":
                print(f"model={MODEL}  yolo={runner.yolo}  workdir={runner.workdir}  turns={len(messages)}")
            else:
                print("commands: /yolo (toggle command confirmation), /status, exit")
            continue
        messages.append({"role": "user", "content": user})
        try:
            agent_turn(client, messages, runner, io, store=store)
        except anthropic.APIError as exc:
            print(f"\n[api error] {exc}", file=sys.stderr)
        finally:
            store.save_transcript(messages, MODEL)


if __name__ == "__main__":
    main()
