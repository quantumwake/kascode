"""Filesystem session store: per-session archive under
<workdir>/.agent/sessions/<session-id>/. Holds the running transcript
(autosaved every turn, resumable via --resume) and compaction events (the full
original transcript next to the summary that replaced it, so no context is ever
silently lost).
"""

import json
import pathlib
import time

from ...core.transcript import jsonable


class SessionStore:
    TRANSCRIPT = "transcript.json"

    def __init__(self, workdir: pathlib.Path, session_id: str | None = None) -> None:
        self.root = pathlib.Path(workdir) / ".agent" / "sessions"
        self.id = session_id or time.strftime("%Y%m%d-%H%M%S")
        self.dir = self.root / self.id
        self.compactions = len(list(self.dir.glob("compaction-*.json"))) if self.dir.exists() else 0

    def save_transcript(
        self, messages: list, model: str | None = None, paused: bool = False
    ) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        first = next((m for m in messages if m.get("role") == "user"), None)
        title = ""
        if first is not None:
            content = first["content"]
            title = (content if isinstance(content, str) else json.dumps(jsonable(content)))[:80]
        with open(self.dir / self.TRANSCRIPT, "w") as f:
            json.dump(
                {
                    "id": self.id,
                    "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model": model,
                    "title": title,
                    "paused": paused,
                    "messages": jsonable(messages),
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
                    "original_messages": jsonable(original_messages),
                },
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        return path
