"""Local lexical retrieval (BM25 via sqlite FTS5) over the workspace + session
memory. Fully offline, no extra model — complements grep with *ranked*,
cross-file, cross-session recall, including content that compaction dropped
from the live context.

This is the v1 retriever. The interface (index/search) is deliberately small
so a hybrid vector half (sqlite-vec + a local mlx embedder, reciprocal-rank
fused with these BM25 hits) can layer on without touching callers.
"""

import hashlib
import json
import pathlib
import re
import sqlite3

CODE_EXT = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".lua",
}
TEXT_EXT = {".md", ".txt", ".rst", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".jinja"}
SKIP_DIRS = {
    ".git",
    ".agent",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
    ".mypy_cache",
    ".pytest_cache",
}
MAX_FILE = 1_000_000  # skip files larger than ~1 MB
CHUNK_LINES = 60  # hard cap on chunk size (lines)
# Structural boundary: a definition starting at low indent (keeps functions /
# classes whole instead of slicing mid-body). Language-agnostic-ish.
DEF_RE = re.compile(
    r"^(\s{0,4})(def |class |func |function |async def |fn |impl |"
    r"public |private |protected |export |const |type |interface |struct )"
)


def _chunk_code(text: str) -> list[tuple[int, int, str]]:
    """(start_line, end_line, body) split on def/class boundaries, size-capped."""
    lines = text.split("\n")
    bounds = [0]
    for i, ln in enumerate(lines):
        # Start a new chunk at each def/class, but only if ≥3 lines past the last
        # boundary — so a run of tiny adjacent defs (overloads, dunders, stubs)
        # stays in one chunk instead of fragmenting into many 1-2 line pieces.
        if DEF_RE.match(ln) and i - bounds[-1] >= 3:
            bounds.append(i)
    bounds.append(len(lines))
    out = []
    for a, b in zip(bounds, bounds[1:], strict=False):
        for s in range(a, b, CHUNK_LINES):
            e = min(b, s + CHUNK_LINES)
            body = "\n".join(lines[s:e]).strip()
            if body:
                out.append((s + 1, e, body))
    return out


def _chunk_text(text: str) -> list[tuple[int, int, str]]:
    lines = text.split("\n")
    out = []
    for s in range(0, len(lines), CHUNK_LINES):
        e = min(len(lines), s + CHUNK_LINES)
        body = "\n".join(lines[s:e]).strip()
        if body:
            out.append((s + 1, e, body))
    return out


# Common words that dilute BM25 ranking on "how does X work"-style queries.
_STOP = {
    "how",
    "does",
    "do",
    "did",
    "when",
    "where",
    "what",
    "why",
    "which",
    "who",
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "and",
    "or",
    "this",
    "that",
    "it",
    "as",
    "at",
    "by",
    "from",
    "we",
    "i",
    "you",
    "should",
    "would",
    "can",
    "use",
    "used",
    "using",
    "into",
}


def _match_query(query: str) -> str:
    """Free text → safe FTS5 MATCH (OR over content words; stopwords dropped so
    rare, meaningful terms dominate the ranking)."""
    tokens = re.findall(r"\w+", query.lower())
    content = [t for t in tokens if t not in _STOP and len(t) > 1]
    # Prefer the rare/meaningful terms; but if the query is ALL stopwords (or
    # single chars), fall back to the raw tokens so we still match something
    # rather than returning an empty (match-nothing) query.
    return " OR ".join(content or tokens)


class RagIndex:
    """sqlite FTS5 BM25 index. Incremental: unchanged files are skipped by hash."""

    def __init__(self, db_path: pathlib.Path) -> None:
        self.db = sqlite3.connect(str(db_path))
        self.db.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, hash TEXT)")
        self.db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
            "body, path UNINDEXED, lines UNINDEXED, source UNINDEXED)"
        )
        self.db.commit()

    # -- indexing -----------------------------------------------------------

    def _put(self, key: str, source: str, chunks: list[tuple[int, int, str]], digest: str) -> None:
        self.db.execute("DELETE FROM chunks WHERE path = ?", (key,))
        self.db.executemany(
            "INSERT INTO chunks(body, path, lines, source) VALUES (?, ?, ?, ?)",
            [(body, key, f"{a}-{b}", source) for a, b, body in chunks],
        )
        self.db.execute("INSERT OR REPLACE INTO files(path, hash) VALUES (?, ?)", (key, digest))

    def index_workspace(self, root: pathlib.Path) -> int:
        """Index code+text files under root. Returns number of files (re)indexed."""
        skip = SKIP_DIRS | _gitignored_dirs(root)
        n = 0
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in (CODE_EXT | TEXT_EXT):
                continue
            if any(part in skip for part in path.parts):
                continue
            try:
                if path.stat().st_size > MAX_FILE:
                    continue
                text = path.read_text(errors="replace")
            except OSError:
                continue
            digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
            key = (
                str(path.relative_to(root))
                if root in path.parents or path.parent == root
                else str(path)
            )
            row = self.db.execute("SELECT hash FROM files WHERE path = ?", (key,)).fetchone()
            if row and row[0] == digest:
                continue  # unchanged
            chunks = _chunk_code(text) if path.suffix in CODE_EXT else _chunk_text(text)
            self._put(key, "code" if path.suffix in CODE_EXT else "docs", chunks, digest)
            n += 1
        self.db.commit()
        return n

    def index_memory(self, root: pathlib.Path) -> int:
        """Index session transcripts + compaction archives so compaction is
        lossless — dropped detail stays recallable."""
        n = 0
        sess = root / ".agent" / "sessions"
        if not sess.exists():
            return 0
        for jf in sess.rglob("*.json"):
            try:
                raw = jf.read_text(errors="replace")
            except OSError:
                continue
            digest = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()
            key = f"memory:{jf.relative_to(sess)}"
            row = self.db.execute("SELECT hash FROM files WHERE path = ?", (key,)).fetchone()
            if row and row[0] == digest:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            text = data.get("summary") or _flatten_messages(
                data.get("messages") or data.get("original_messages") or []
            )
            if not text.strip():
                continue
            self._put(key, "memory", _chunk_text(text), digest)
            n += 1
        self.db.commit()
        return n

    def refresh(self, root: pathlib.Path) -> int:
        return self.index_workspace(root) + self.index_memory(root)

    # -- search -------------------------------------------------------------

    def search(self, query: str, k: int = 8) -> list[dict]:
        match = _match_query(query)
        if not match:
            return []
        rows = self.db.execute(
            "SELECT body, path, lines, source, bm25(chunks) AS score "
            "FROM chunks WHERE chunks MATCH ? ORDER BY score LIMIT ?",
            (match, k),
        ).fetchall()
        return [
            {"body": b, "path": p, "lines": ln, "source": s, "score": sc}
            for b, p, ln, s, sc in rows
        ]


def _gitignored_dirs(root: pathlib.Path) -> set[str]:
    """Simple directory names from .gitignore (bare names / `name/` entries),
    so indexing skips build output, vendored code, and test artifacts."""
    gi = root / ".gitignore"
    out: set[str] = set()
    if not gi.exists():
        return out
    try:
        for line in gi.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "*" in line:
                continue
            name = line.strip("/").split("/")[-1]
            if name:
                out.add(name)
    except OSError:
        pass
    return out


def _flatten_messages(messages: list) -> str:
    parts = []
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    parts.append(b.get("text") or b.get("thinking") or b.get("content") or "")
    return "\n".join(p for p in parts if isinstance(p, str) and p.strip())
