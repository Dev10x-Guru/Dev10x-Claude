"""Herdr roster MCP tool (GH-1984).

The sanctioned read of which Claude sessions Herdr runs, grouped by
repository and by role, so `dev10x-herdr:mission-control` never parses
`herdr` output by hand. Read-only: it never prompts or moves a pane.
"""

from __future__ import annotations

from typing import Any

from dev10x.core.domain.common.result import Result
from dev10x.core.mcp._app import mcp_tool
from dev10x.core.subprocess_utils import effective_cwd
from dev10x.herdr.probes import get_roster


@mcp_tool
async def herdr_roster(
    repo_root: str | None = None,
    cwd: str | None = None,
) -> Result[dict[str, Any]]:
    """List live Herdr Claude sessions grouped by repository and role (GH-1984).

    A session's role comes from its Herdr workspace binding: `main` for the
    repository's own checkout, `worktree` for a linked worktree, and
    `unbound` for a workspace with no worktree binding. Each repository
    names one `coordinator`: the main session whose workspace label equals
    the repository name, else the lowest-numbered main workspace.

    Args:
        repo_root: Absolute main-checkout path; limits `repos` to that
            repository and leaves `unbound` empty.
        cwd: Absolute effective working directory (GH-979). It also sets
            `caller`, so a session can tell whether it runs in a main
            checkout (repo mode) or elsewhere (global mode).

    Returns:
        Dictionary with keys `repos` (repo_name, repo_key, repo_root,
        coordinator, main_sessions, worktree_sessions), `unbound` and
        `caller` (role `main` / `worktree` / `unbound` / `outside`,
        repo_root, workspace_id). Each session carries pane_id, name,
        status, role, workspace_id, workspace_label, checkout_path, cwd
        and terminal_title. `{"error": ...}` when herdr is missing, times
        out or returns an unreadable payload.
    """
    return get_roster(cwd=effective_cwd() or "", repo_root=repo_root or "")
