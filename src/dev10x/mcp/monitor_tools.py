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
    wait_out_pending: bool = True,
    wait_for: list[str] | None = None,
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
        max_polls: Maximum number of polls (default 40, keeping the
            in-loop poll budget at 1230s and this call's subprocess cap
            at 1320s, both under the ~1800s MCP idle-timeout — they are
            two different ceilings, GH-808 F2, GH-1104)
        wait_out_pending: Under ``wait``, keep polling through a failed
            NON-required check until no leg is pending (default True,
            GH-1065). A failed REQUIRED check still returns immediately.
            Set False for the old return-on-first-failure behaviour.
        wait_for: Check names that must settle before the wait ends, even
            when a REQUIRED check has already failed (GH-1138). On any
            branch carrying ``fixup!`` commits the required
            ``git-history-linting`` leg fails by design until squash, so
            "required red + advisory legs pending" is routine — and
            ``wait_out_pending`` does not cover it. Pass the bot legs
            (e.g. ``["claude-review", "hygiene-review"]``) when the next
            step would invalidate what they anchor to, such as a groom
            that force-pushes the SHAs their comments reference. The poll
            budget still bounds the wait.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with verdict (green/pending/failing/conflicting/empty/
        infra_unavailable), mergeable status, and check details. A
        ``wait=true`` call that exhausts its budget while checks never
        register returns ``infra_unavailable`` — the caller re-invokes or
        escalates rather than treating it as a transient pending. A
        ``failing`` verdict from a ``wait_out_pending`` run names the failed
        leg in ``checks`` and reports ``pending: 0``, so the caller can tell
        an advisory red apart from an unfinished run.
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
                wait_out_pending=wait_out_pending,
                wait_for=wait_for,
            )
        )
