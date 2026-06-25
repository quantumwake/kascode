"""Port conformance (v3 Phase 5): every adapter must structurally satisfy the
@runtime_checkable Protocol the core depends on. isinstance here fails fast at
test time if a method is renamed/removed, instead of at runtime mid-session —
closing the "duck-typed, unenforced" gap from the analysis. No model/server.

Run:  uv run python tests/test_ports.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, ".")

from agent.adapters.storage.filesystem import SessionStore
from agent.adapters.tools.executor import ToolRunner
from agent.adapters.ui.console import ConsoleIO
from agent.adapters.workspace.git import GitWorkspace
from agent.core.subagent import SubagentIO
from agent.ports.storage import SessionStorePort
from agent.ports.tools import ToolExecutor
from agent.ports.ui import AgentIO
from agent.ports.workspace import WorkspacePort
from agent.tui.io import TuiIO

tmp = pathlib.Path(tempfile.mkdtemp())
console = ConsoleIO("http://127.0.0.1:9")

# --- AgentIO: every presentation adapter satisfies the UI port -------------
assert isinstance(console, AgentIO), "ConsoleIO must satisfy AgentIO"
assert isinstance(TuiIO(object()), AgentIO), "TuiIO must satisfy AgentIO"
assert isinstance(SubagentIO(console), AgentIO), "SubagentIO must satisfy AgentIO"
print("AgentIO conformance: OK")

# --- ToolExecutor: the runner satisfies the tool port ----------------------
runner = ToolRunner(tmp, yolo=False, io=console)
assert isinstance(runner, ToolExecutor), "ToolRunner must satisfy ToolExecutor"
print("ToolExecutor conformance: OK")

# --- SessionStorePort / WorkspacePort --------------------------------------
assert isinstance(SessionStore(tmp), SessionStorePort), "SessionStore must satisfy SessionStorePort"
assert isinstance(GitWorkspace(tmp, console), WorkspacePort), (
    "GitWorkspace must satisfy WorkspacePort"
)
print("SessionStore / Workspace conformance: OK")

print("all port conformance tests passed")
