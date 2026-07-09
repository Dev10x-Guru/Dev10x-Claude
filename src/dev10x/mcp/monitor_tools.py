"""Monitor MCP tool registrations (split from github_tools.py, GH-585)."""

from __future__ import annotations

from dev10x.domain.common.result import to_wire
from dev10x.mcp._app import server


@server.tool()
async def ci_check_status(
    pr_number: int,
    repo: str,
    required_only: bool = False,
    wait: bool = False,
    poll_interval: int = 30,
    initial_wait: int = 60,
    max_polls: int = 40,
    cwd: str | None = None,
) -> dict:
    """Check CI status for a PR and return a structured verdict.

    Args:
        pr_number: PR number
        repo: Repository in owner/repo format
        required_only: Only check required status checks
        wait: Poll until terminal verdict (green/failing/conflicting)
        poll_interval: Seconds between polls (default 30)
        initial_wait: Initial wait before first poll (default 60)
        max_polls: Maximum number of polls (default 40, keeping the total
            wait ~1320s under the ~1800s MCP idle-timeout, GH-808 F2)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with verdict (green/pending/failing/conflicting/empty/
        infra_unavailable), mergeable status, and check details. A
        ``wait=true`` call that exhausts its budget while checks never
        register returns ``infra_unavailable`` — the caller re-invokes or
        escalates rather than treating it as a transient pending.
    """
    from dev10x import monitor as mon
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(
            await mon.ci_check_status(
                pr_number=pr_number,
                repo=repo,
                required_only=required_only,
                wait=wait,
                poll_interval=poll_interval,
                initial_wait=initial_wait,
                max_polls=max_polls,
            )
        )
