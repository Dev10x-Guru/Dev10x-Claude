"""MCP server registration for the Dev10x CLI server.

Tool handlers now live in per-domain modules under `src/dev10x/mcp/`:
  - github_tools.py  — GitHub/PR/issue/milestone/review/CI/release handlers
  - git_tools.py     — git push, rebase, worktree handlers
  - plan_tools.py    — plan-sync handlers
  - audit_tools.py   — session audit and hook-log handlers
  - misc_tools.py    — mktmp, slack, permission, skill-index, upgrade handlers

This module imports all of them (triggering @server.tool() registration)
and re-exports their names for backward-compatible attribute access.
The `server` object is also re-exported so callers that do
`from dev10x.mcp.server_cli import server` keep working.

Split as part of GH-243/A6.
"""

from __future__ import annotations

# GH-979: every CWD-sensitive tool accepts an optional `cwd` argument.
# Skills must pass the session's effective working directory (e.g. the
# worktree path after EnterWorktree) so subprocess_utils binds it via
# the `_effective_cwd` ContextVar before any git/gh subprocess fires.
# When `cwd` is None, behavior is unchanged from pre-GH-979 (subprocess
# inherits the MCP server's startup CWD).
# Importing the tool modules triggers @server.tool() registration.
# Importing knowledge_resources triggers @server.resource() registration
# (GH-339). Importing knowledge_prompts triggers @server.prompt()
# registration (GH-340).
from dev10x.mcp import (  # noqa: E402, F401
    audit_tools,
    git_tools,
    github_tools,
    knowledge_prompts,
    knowledge_resources,
    misc_tools,
    plan_tools,
)
from dev10x.mcp._app import (
    server,  # noqa: F401  (re-exported for callers importing server from server_cli)
)
from dev10x.mcp.audit_tools import *  # noqa: E402, F401, F403
from dev10x.mcp.git_tools import *  # noqa: E402, F401, F403
from dev10x.mcp.github_tools import *  # noqa: E402, F401, F403
from dev10x.mcp.misc_tools import *  # noqa: E402, F401, F403
from dev10x.mcp.plan_tools import *  # noqa: E402, F401, F403


def main() -> None:
    from dev10x.mcp.wiring import select_transport_with_daemon_fallback

    server.run(transport=select_transport_with_daemon_fallback())
