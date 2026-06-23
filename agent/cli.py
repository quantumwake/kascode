"""kas agent — CLI composition root.

Parses args, applies them to the shared config, wires the concrete adapters
(ConsoleIO / TUI, ToolRunner, SessionStore) to the core loop, and dispatches:
`kas serve ...` (inference daemon), `kas --sessions`, `kas --resume`, a one-shot
task, the TUI, or the plain REPL.
"""

import argparse
import os
import pathlib
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


def serve_main(argv: list[str]) -> None:
    """`kas serve` — run the inference server. Daemonizes by default."""
    import signal
    import subprocess

    ap = argparse.ArgumentParser(prog="kas serve")
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
    # subcommands: `kas serve ...` and `kas agent ...` (bare `kas` = agent)
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve_main(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "agent":
        del sys.argv[1]  # strip so the agent parser sees the rest

    ap = argparse.ArgumentParser(prog="kas", description="kas — your local agent")
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
        "--rag",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("KAS_RAG", "1") != "0",
        help="recall tool — local BM25 over code/docs/memory (on by default; --no-rag to disable)",
    )
    ap.add_argument(
        "--sandbox",
        action="store_true",
        default=os.environ.get("KAS_SANDBOX") == "1",
        help="jail the file tools to the workdir (reject absolute/.. escapes)",
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
        "--resume",
        nargs="?",
        const="__latest__",
        metavar="SESSION_ID",
        help="resume a saved session (latest for this workdir if no id given)",
    )
    ap.add_argument("--sessions", action="store_true", help="list resumable sessions and exit")
    ap.add_argument("task", nargs="*", help="optional one-shot task; omit for interactive mode")
    args = ap.parse_args()
    config.MAX_TOKENS = args.max_tokens
    config.COMPACT_AT = args.compact_at
    config.BASE_URL = args.base_url
    served, context_limit = served_info(config.BASE_URL)
    config.MODEL = args.model or served
    if config.MODEL is None:
        sys.exit(f"server at {config.BASE_URL} is not reachable — start it with: make start")

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
            rag=args.rag,
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
            rag=args.rag,
            context_limit=context_limit,
            sandbox=args.sandbox,
            art=args.art,
            theme=args.theme,
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
        rag=args.rag,
        context_limit=context_limit,
        sandbox=args.sandbox,
    )
    print_console(model=config.MODEL, extra=f"workdir {workdir} · yolo {args.yolo}")
    print("REPL commands: /yolo  /status  exit · at a confirm prompt: y / N / a=always")
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print_resume_hint()
            return
        if not user or user in ("exit", "quit"):
            print_resume_hint()
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
            else:
                print(
                    "commands: /yolo  /ctx [<tokens>|max|auto|valve on|valve off]  "
                    "/kv  /art  /status  exit"
                )
            continue
        messages.append({"role": "user", "content": user})
        try:
            agent_turn(client, messages, runner, io, store=store)
        except anthropic.APIError as exc:
            print(f"\n[api error] {exc}", file=sys.stderr)
        finally:
            store.save_transcript(messages, config.MODEL)
