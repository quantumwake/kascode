"""kas agent — CLI composition root.

Parses args, applies them to the shared config, wires the concrete adapters
(ConsoleIO / TUI, ToolRunner, SessionStore) to the core loop, and dispatches:
`kas serve ...` (inference daemon), `kas --sessions`, `kas --resume`, a one-shot
task, the TUI, or the plain REPL.
"""

import argparse
import os
import pathlib
import subprocess
import sys
import time

import anthropic
import httpx

from . import config
from .adapters.storage.filesystem import SessionStore
from .adapters.tools.executor import ToolRunner
from .adapters.ui.console import ConsoleIO
from .config import served_info
from .core.loop import agent_turn


def _server_state() -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """The ~/.kas dir plus the server pid/log paths (created on first use)."""
    state = pathlib.Path.home() / ".kas"
    state.mkdir(exist_ok=True)
    return state, state / "server.pid", state / "server.log"


def _spawn_server(port: int, model: str | None = None) -> subprocess.Popen:
    """Spawn the inference server as a detached process and record its pid.

    A distinct `python -m server.cli` process (not a re-entry of kas) avoids the
    pidfile self-detection footgun.
    """
    _, pidf, logf = _server_state()
    env = {**os.environ}
    if model:
        env["KAS_MODEL"] = model
    log = open(logf, "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.cli", "--port", str(port)],
        stdout=log,
        stderr=log,
        start_new_session=True,
        env=env,
    )
    pidf.write_text(str(proc.pid))
    return proc


def _wait_for_server(base: str, proc: subprocess.Popen, attempts: int = 180) -> bool:
    """Poll base/v1/models until it answers; False if the process dies or times out.

    The liveness check comes BEFORE the probe each iteration: if our child exited
    (e.g. it hit an occupied port and the preflight aborted it), an unrelated
    server still answering on `base` must not be mistaken for ours."""
    for _ in range(attempts):
        if proc.poll() is not None:  # our child died — don't be fooled by an orphan
            return False
        try:
            httpx.get(base + "/v1/models", timeout=1)
            return True
        except Exception:
            time.sleep(2)
    return False


def _is_local_url(url: str) -> bool:
    return httpx.URL(url).host in ("127.0.0.1", "localhost", "0.0.0.0", "::1")


def _pick_model() -> str | None:
    """Prompt for which model to load: a number from the locally downloaded list,
    a typed Hugging Face model id, or empty for the server's default. Returns the
    chosen id, or None for the default.
    """
    from scripts.select_model import model_info

    models = model_info()
    if models:
        print("available local models:")
        for i, m in enumerate(models, 1):
            tag = m["size_h"] + ("" if m["complete"] else ", partial")
            print(f"  {i}) {m['id']}  [{tag}]")
        prompt = "pick a number, or type a HF model id (Enter = server default): "
    else:
        prompt = "no local models found — type a HF model id (Enter = server default): "
    try:
        raw = input(prompt).strip()
    except EOFError:
        return None
    if not raw:
        return None  # server default
    if raw.isdigit() and models and 1 <= int(raw) <= len(models):
        return models[int(raw) - 1]["id"]
    return raw  # an HF model id typed verbatim (downloaded on first load if needed)


def _offer_to_start_server(base_url: str, model: str | None) -> tuple[str | None, int | None]:
    """The server is unreachable. If base_url is local and we're on a TTY, offer
    to start one and wait for it to load. Returns (served_model, context_limit)
    on success, else (None, None) — the caller then exits with the usual hint.
    """
    if not _is_local_url(base_url) or not sys.stdin.isatty():
        return None, None  # remote server, or non-interactive — not ours to start
    try:
        ans = input(f"No kas server running at {base_url}. Start one now? [Y/n] ").strip().lower()
    except EOFError:
        return None, None
    if ans not in ("", "y", "yes"):
        return None, None
    if model is None:  # no --model given: let the user pick or type one
        model = _pick_model()
    port = httpx.URL(base_url).port or 8765
    print(
        f"starting kas server{f' with {model}' if model else ''} — the first load "
        "pulls the model into the GPU and can take a while…"
    )
    proc = _spawn_server(port, model=model)
    if _wait_for_server(base_url, proc):
        print("server ready.")
        return served_info(base_url)
    print("server failed to start — check the log with: kas serve --logs")
    return None, None


def serve_main(argv: list[str]) -> None:
    """`kas serve` — run the inference server. Daemonizes by default."""
    import signal

    from scripts.version import kas_version

    ap = argparse.ArgumentParser(prog="kas serve")
    ap.add_argument("--version", action="version", version=f"kas {kas_version()}")
    ap.add_argument("--port", type=int, default=int(os.environ.get("KAS_PORT", "8765")))
    ap.add_argument("--model", default=None, help="model repo to load")
    ap.add_argument(
        "--daemon",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run in background (default; --no-daemon to run in foreground)",
    )
    ap.add_argument("--stop", action="store_true", help="stop the running server")
    ap.add_argument("--status", action="store_true", help="show server status")
    ap.add_argument("--logs", action="store_true", help="tail the server log")
    a = ap.parse_args(argv)

    _, pidf, logf = _server_state()
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
            os.killpg(os.getpgid(p), signal.SIGTERM) if hasattr(os, "getpgid") else os.kill(
                p, signal.SIGTERM
            )
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

    # daemonize: spawn the SEPARATE kas-server process, detached, then wait.
    proc = _spawn_server(a.port)
    print(f"starting kas server (pid {proc.pid}) on {base} — loading model…")
    if _wait_for_server(base, proc):
        print(f"ready: {base}  (logs: kas serve --logs · stop: kas serve --stop)")
    else:
        print(f"server exited early or slow to start — see {logf} (kas serve --logs)")


def _build_parser() -> argparse.ArgumentParser:
    """The `kas` (agent) argument parser. Defaults read from config/env so the
    KAS_* envvars and the flags compose."""
    from scripts.version import kas_version

    ap = argparse.ArgumentParser(prog="kas", description="kas — your local agent")
    ap.add_argument("--version", action="version", version=f"kas {kas_version()}")
    ap.add_argument("--yolo", action="store_true", help="run bash commands without confirmation")
    ap.add_argument("--workdir", default=".", help="working directory for tools")
    ap.add_argument(
        "--model", default=config.MODEL, help="model id (default: whatever the server loaded)"
    )
    ap.add_argument("--base-url", default=config.BASE_URL, help="inference server URL")
    ap.add_argument(
        "--max-tokens", type=int, default=config.MAX_TOKENS, help="output token cap per response"
    )
    ap.add_argument(
        "--compact-at",
        type=int,
        default=config.COMPACT_AT,
        help="auto-compact context past this many input tokens (0 disables)",
    )
    ap.add_argument("--plain", action="store_true", help="plain REPL instead of the TUI")
    ap.add_argument(
        "--checkpoint",
        action="store_true",
        help="commit per-turn checkpoints even when workdir is a pre-existing repo",
    )
    ap.add_argument(
        "--net",
        action="store_true",
        default=os.environ.get("KAS_NET") == "1",
        help="enable web_search/web_fetch (off by default — kas is offline)",
    )
    ap.add_argument(
        "--memory",
        dest="memory",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("KAS_MEMORY", "1") != "0",
        help="recall tool — local memory over code/docs/sessions "
        "(on by default; --no-memory to disable)",
    )
    ap.add_argument(
        "--sandbox",
        action="store_true",
        default=os.environ.get("KAS_SANDBOX") == "1",
        help="(gated) real sandboxing is a future microVM-isolation extension; the "
        "old file-tools-only jail was removed because bash escaped it (false security)",
    )
    ap.add_argument(
        "--art",
        action="store_true",
        default=os.environ.get("KAS_ART") == "1",
        help="enable generate_image (local FLUX via mflux; needs the 'art' extra)",
    )
    ap.add_argument(
        "--theme",
        default=os.environ.get("KAS_THEME", "amber"),
        help="initial TUI colour theme: amber (default), matrix, ice, fire, neon, "
        "synthwave, rainbow, purple, mono (also switchable live with /theme)",
    )
    ap.add_argument(
        "--mdui",
        choices=["off", "md", "rules", "all"],
        default=os.environ.get("KAS_MDUI", "off"),
        help="EXPERIMENTAL markdown UI (default off, while the rich rendering is "
        "stabilised): md=render answers as markdown, rules=you/kas turn separators, "
        "all=both",
    )
    ap.add_argument(
        "--mouse-select",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("KAS_MOUSE_SELECT", "1") != "0",
        help="mouse text-selection in the output view (on by default; "
        "--no-mouse-select if it misbehaves in your terminal)",
    )
    ap.add_argument(
        "--resume",
        nargs="?",
        const="__latest__",
        metavar="SESSION_ID",
        help="resume a saved session (latest for this workdir if no id given)",
    )
    ap.add_argument("--sessions", action="store_true", help="list resumable sessions and exit")
    ap.add_argument("task", nargs="*", help="optional one-shot task; omit for interactive mode")
    return ap


def _run_plain_repl(client, io, runner, store, messages: list, workdir, resume_hint) -> None:
    """The --plain / non-TTY REPL: read lines, handle a small command set, and
    run a turn per message. resume_hint() prints the resume command on exit."""
    print("REPL commands: /yolo  /status  exit · at a confirm prompt: y / N / a=always")
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            resume_hint()
            return
        if not user or user in ("exit", "quit"):
            resume_hint()
            return
        if user.startswith("/"):
            if user == "/yolo":
                runner.yolo = not runner.yolo
                state = (
                    "ON — commands run without confirmation"
                    if runner.yolo
                    else "OFF — commands need approval"
                )
                print(f"yolo {state}")
            elif user == "/status":
                print(
                    f"model={config.MODEL}  yolo={runner.yolo}  "
                    f"workdir={runner.workdir}  turns={len(messages)}"
                )
            elif user == "/ctx" or user.startswith("/ctx "):
                from agent.core.compaction import ctx_command

                print(ctx_command(runner, user[len("/ctx") :]))
            elif user == "/art":
                runner.art = not runner.art
                print(
                    f"image generation {'ON (needs mflux: uv add mflux)' if runner.art else 'OFF'}"
                )
            elif user == "/kv" or user.startswith("/kv "):
                print(runner.kv_status(user[len("/kv") :]))
            elif user == "/self-skill":
                from agent.core.self_skill import self_skill

                self_skill(client, io, config.MODEL, workdir, max_tokens=config.MAX_TOKENS)
            elif user == "/ai-wellbeing":
                from agent.core.ai_wellbeing import assess_wellbeing

                assess_wellbeing(client, io, messages, config.MODEL, workdir)
            elif user == "/spec":
                from agent.core.spec import PROJECT_KINDS, spec_seed

                for i, k in enumerate(PROJECT_KINDS, 1):
                    print(f"  {i}) {k}")
                try:
                    pick = int(input("what are you building? #: ")) - 1
                    kind = PROJECT_KINDS[pick]
                except (ValueError, IndexError, EOFError):
                    print("cancelled")
                    continue
                messages.append({"role": "user", "content": spec_seed(kind)})
                try:
                    agent_turn(client, messages, runner, io, store=store)
                except anthropic.APIError as exc:
                    print(f"\n[api error] {exc}", file=sys.stderr)
                finally:
                    store.save_transcript(messages, config.MODEL)
                continue
            else:
                print(
                    "commands: /yolo  /ctx [<tokens>|max|auto|valve on|valve off]  "
                    "/kv  /art  /status  /ai-wellbeing  exit"
                )
            continue
        messages.append({"role": "user", "content": user})
        try:
            agent_turn(client, messages, runner, io, store=store)
        except anthropic.APIError as exc:
            print(f"\n[api error] {exc}", file=sys.stderr)
        finally:
            store.save_transcript(messages, config.MODEL)


def main() -> None:
    # subcommands: `kas serve ...`, `kas doctor ...`, `kas agent ...` (bare `kas` = agent)
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve_main(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from scripts.doctor import main as doctor_main

        sys.exit(doctor_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "models":
        from scripts.models import main as models_main

        sys.exit(models_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "agent":
        del sys.argv[1]  # strip so the agent parser sees the rest

    args = _build_parser().parse_args()
    if args.sandbox:
        # Honest gate: a file-tools-only jail gave false security (bash escaped
        # it), so it was removed. True isolation is a future microVM extension.
        sys.exit(
            "sandbox mode is gated behind the microVM isolation extension, which isn't "
            "built yet. kas refuses --sandbox rather than imply a containment it can't "
            "enforce (bash would still reach the rest of the system). Run without it."
        )
    config.MAX_TOKENS = args.max_tokens
    config.COMPACT_AT = args.compact_at
    config.BASE_URL = args.base_url
    served, context_limit = served_info(config.BASE_URL)
    if served is None:
        # Server down: offer to start a local one (interactive TTY only).
        served, context_limit = _offer_to_start_server(config.BASE_URL, args.model)
    config.MODEL = args.model or served
    if config.MODEL is None:
        sys.exit(f"server at {config.BASE_URL} is not reachable — start it with: kas serve")

    workdir = pathlib.Path(args.workdir).resolve()

    if args.sessions:
        sessions = SessionStore.sessions(workdir)
        if not sessions:
            print(f"no saved sessions under {workdir}/.agent/sessions/")
            return
        for s in sessions:
            print(f"{s['id']}  {s['updated']}  {s['messages']:>3} msgs  {s['title']}")
        print(f"\nresume with: python -m agent --resume <SESSION_ID> --workdir {workdir}")
        return

    # Resilient transport: the server pings every few seconds during long
    # prefills so the stream never goes silent (httpx read timeout is per-gap,
    # not total), and max_retries reconnects on a dropped connection.
    client = anthropic.Anthropic(
        base_url=config.BASE_URL,
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
            sys.exit(
                f"no resumable session{f' {wanted!r}' if wanted else ''} "
                f"under {workdir}/.agent/sessions/"
            )
        print(f"resumed session {store.id} ({len(messages)} messages)")
    if store is None:
        store = SessionStore(workdir)

    def print_resume_hint() -> None:
        """On exit, show how to pick this session back up."""
        if not messages:
            return  # nothing was said this session — nothing to resume
        cmd = f"kas --resume {store.id}"
        if workdir != pathlib.Path.cwd():
            cmd += f" --workdir {workdir}"
        print(f"\nresume this session with:\n  {cmd}")

    from scripts.banner import print_console

    if args.task:  # one-shot
        io = ConsoleIO(config.BASE_URL)
        runner = ToolRunner(
            workdir,
            yolo=args.yolo,
            io=io,
            checkpoint=args.checkpoint,
            net=args.net,
            rag=args.memory,
            context_limit=context_limit,
            sandbox=args.sandbox,
            compact_at=config.COMPACT_AT,
            art=args.art,
        )
        print_console(model=config.MODEL, extra=f"workdir {workdir} · yolo {args.yolo}")
        messages.append({"role": "user", "content": " ".join(args.task)})
        try:
            agent_turn(client, messages, runner, io, store=store)
        finally:
            store.save_transcript(messages, config.MODEL)
        return

    if not args.plain and sys.stdin.isatty():  # interactive: TUI with steering
        from agent.tui import AgentApp

        AgentApp(
            client=client,
            model=config.MODEL,
            base_url=config.BASE_URL,
            workdir=workdir,
            yolo=args.yolo,
            max_tokens=config.MAX_TOKENS,
            compact_at=config.COMPACT_AT,
            store=store,
            messages=messages,
            checkpoint=args.checkpoint,
            net=args.net,
            rag=args.memory,
            context_limit=context_limit,
            sandbox=args.sandbox,
            art=args.art,
            theme=args.theme,
            mdui=args.mdui,
            mouse_select=args.mouse_select,
        ).run()
        print_resume_hint()
        return

    # plain REPL fallback
    io = ConsoleIO(config.BASE_URL)
    runner = ToolRunner(
        workdir,
        yolo=args.yolo,
        io=io,
        checkpoint=args.checkpoint,
        net=args.net,
        rag=args.memory,
        context_limit=context_limit,
        sandbox=args.sandbox,
    )
    print_console(model=config.MODEL, extra=f"workdir {workdir} · yolo {args.yolo}")
    _run_plain_repl(client, io, runner, store, messages, workdir, print_resume_hint)
