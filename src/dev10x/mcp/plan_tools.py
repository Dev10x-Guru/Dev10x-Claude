"""Plan/Task MCP tool registrations (split from server_cli.py, GH-243/A6)."""

from __future__ import annotations

from dev10x.domain.common.result import to_wire
from dev10x.mcp._app import server


@server.tool()
async def plan_sync_set_context(
    args: list[str],
    cwd: str | None = None,
) -> dict:
    """Update plan context with key=value pairs.

    Args:
        args: K=V pairs (e.g., ["work_type=feature", "tickets=[...]"])
        cwd: Effective working directory (GH-979). The plan file
            location is computed relative to this repo's toplevel.

    Returns:
        Dictionary with keys: success (bool), updated_keys (list[str])
    """
    from dev10x import plan as plan_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(await plan_tools.set_context(args=args))


@server.tool()
async def plan_sync_json_summary(cwd: str | None = None) -> dict:
    """Retrieve the current plan as a JSON summary.

    Args:
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with plan metadata, context, and task list.
        Empty dict if a plan file exists but holds no metadata.
        `{"error": "Not in a git repository"}` when run outside a repo.
    """
    from dev10x import plan as plan_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(await plan_tools.json_summary())


@server.tool()
async def plan_sync_archive(cwd: str | None = None) -> dict:
    """Archive the current plan to a timestamped file and remove active plan.

    Args:
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), archive_name (str)
    """
    from dev10x import plan as plan_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(await plan_tools.archive())
