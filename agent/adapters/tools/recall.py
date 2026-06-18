"""Opt-in local recall tool (--rag): ranked BM25 over code/docs/session memory.
Holds the lazily-built index for the workdir and formats hits for the model.
"""

import pathlib

from ...config import _truncate


class Recaller:
    def __init__(self, workdir: pathlib.Path) -> None:
        self.workdir = workdir
        self._index = None

    def search(self, query: str, k: int = 8) -> tuple[str, bool]:
        from ..retrieval.bm25 import RagIndex

        if self._index is None:
            (self.workdir / ".agent").mkdir(parents=True, exist_ok=True)
            self._index = RagIndex(self.workdir / ".agent" / "rag.db")
        try:
            self._index.refresh(self.workdir)  # incremental: unchanged files skipped
        except Exception as exc:
            return f"recall index refresh failed: {type(exc).__name__}: {exc}", True
        hits = self._index.search(query, k=max(1, min(int(k or 8), 20)))
        if not hits:
            return f"no matches for {query!r} (try grep for exact strings)", False
        out = []
        for i, h in enumerate(hits, 1):
            snippet = h["body"] if len(h["body"]) < 600 else h["body"][:600] + "…"
            out.append(f"{i}. {h['path']}:{h['lines']} [{h['source']}]\n{snippet}")
        return _truncate("\n\n".join(out)), False
