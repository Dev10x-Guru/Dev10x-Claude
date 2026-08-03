"""Task-index MCP tool registrations (GH-1009, ADR-0018 D5).

These exist so the park family never reaches its store with the Write/Edit
tool. The store now lives outside every repo, but routing the writes through
the MCP server is what keeps them gate-free — the self-settings gate is a
*tool* phenomenon, so an agent hand-editing the file would still prompt.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.common.result import to_wire
from dev10x.mcp._app import server


@server.tool()
async def task_index_get(cwd: str | None = None) -> dict:
    """Read the repo's park/session task index (GH-1009).

    Replaces reading `.claude/Dev10x/session.yaml` directly. Keyed by the
    repo's git common dir, so every worktree of a repo shares one index.
    Falls back to the retired per-checkout file for one release; when that
    happens `legacy_read` is true and `legacy_path` names the file.

    Args:
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: path, repo_name, exists, legacy_read,
        legacy_path, tasks, continuation_prompt, insights, branch, tickets,
        wrapped_at. `{"error": "Not in a git repository"}` outside a repo.
    """
    from dev10x.session import task_index
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(task_index.read_index(cwd=cwd))


@server.tool()
async def task_index_append(entry: dict[str, Any], cwd: str | None = None) -> dict:
    """Append one deferral entry to the repo's task index (GH-1009).

    The write the park family performs instead of Write/Edit-ing
    `.claude/Dev10x/session.yaml`. On the first write after the rehome, any
    entries still in the retired file are folded forward first, so parked
    items are not orphaned; `folded_legacy` names that file when it happens.

    Args:
        entry: Task entry. `subject` and `source` are required; `status` and
            `metadata` are the conventional optional keys. `source` names the
            writer (`park`, `code-todo`, `slack-reminder`, `pr-bookmark`,
            `session-wrap-up`) so `park-discover` can group by origin.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: path, repo_name, task_count, folded_legacy.
    """
    from dev10x.session import task_index
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(task_index.append_task(entry=entry, cwd=cwd))


@server.tool()
async def task_index_set(
    continuation_prompt: str | None = None,
    insights: list[str] | None = None,
    branch: str | None = None,
    tickets: list[str] | None = None,
    wrapped_at: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Write session-wrap-up state onto the repo's task index (GH-1009).

    Only the supplied fields are written, so refreshing the continuation
    prompt cannot blank the parked `tasks` list. `branch`/`tickets` are a
    wrap-up record feeding `park-discover`'s live-or-stale classification
    (GH-782) — they are NOT the session-adoption gate's identity, which comes
    from plan-sync (ADR-0018 D2).

    Args:
        continuation_prompt: One-paragraph resume summary.
        insights: Lessons/patterns carried to the next session.
        branch: Branch the session wrapped on.
        tickets: Ticket IDs the session covered.
        wrapped_at: ISO-8601 timestamp; the caller owns the clock.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: path, repo_name, updated_keys, folded_legacy.
    """
    from dev10x.session import task_index
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(
            task_index.set_session_state(
                continuation_prompt=continuation_prompt,
                insights=insights,
                branch=branch,
                tickets=tickets,
                wrapped_at=wrapped_at,
                cwd=cwd,
            )
        )
