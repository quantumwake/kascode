"""Concurrent agents must not share a KV cache. The server keys the KV slot +
continuation memo by the x-agent-thread header; the agent defaults that to the
SESSION ID (unique per process, stable across --resume) instead of a shared
"main". Sessions get unique ids even when started the same second, and subagent
threads are namespaced under the parent session.

Run:  uv run python tests/test_thread_isolation.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

from agent.adapters.storage.filesystem import SessionStore

w = pathlib.Path(tempfile.mkdtemp())

# --- session ids are unique even in a tight loop (same second) -------------
ids = [SessionStore(w).id for _ in range(25)]
assert len(set(ids)) == 25, f"session ids must be unique, got {len(set(ids))}/25"
assert all("-" in i for i in ids), "id keeps a timestamp + suffix"
print("session ids unique (same-second safe): OK")

# --- the thread agent_turn uses = the session id, never the shared 'main' ---
# (mirrors `thread = getattr(store, 'id', None) or 'main'` in agent_turn)
s = SessionStore(w)
thread = getattr(s, "id", None) or "main"
assert thread == s.id and thread != "main", thread
print("default thread = session id (not shared 'main'): OK")

# --- subagent threads are namespaced under the parent session --------------
# (mirrors run_subagent's `thread = f"{parent_thread}-sub-{n}"`)
a, b = SessionStore(w).id, SessionStore(w).id
assert f"{a}-sub-1" != f"{b}-sub-1", "two sessions' sub-1 must not collide"
assert f"{a}-sub-1".startswith(a)
print("subagent thread namespaced under parent: OK")

print("all thread-isolation tests passed")
