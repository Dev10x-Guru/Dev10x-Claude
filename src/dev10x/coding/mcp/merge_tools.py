from __future__ import annotations

from typing import Any

from dev10x.domain.common.result import Result
from dev10x.mcp._app import mcp_tool


@mcp_tool
async def audit_handoff_report(
    report: dict[str, Any],
    pr_state: dict[str, Any],
    cwd: str | None = None,
) -> Result[dict]:
    """Audit a subagent's pre-merge handoff report before inheriting it (GH-1380, GH-1777).

    Pure and read-only: it compares the report against a fresh ``pr_get``
    response and touches nothing.

    Args:
        report: The worker's handoff report as a JSON object (``head_sha``,
            ``measured_at``, ``checks`` with an observed value per entry).
        pr_state: A fresh ``pr_get`` response for the same PR.
        cwd: Effective working directory (GH-979). Unused by the audit.

    Returns:
        Dictionary with ``verdict`` (``accept`` / ``reject`` /
        ``already_merged``), ``accepted``, ``reasons``, ``merged_at``,
        ``merged_by`` and ``summary``. Anything but ``accepted: true``
        forbids inheriting Checks 1d/5/6 from the report.
    """
    from dev10x.coding import merge

    return await merge.audit_handoff_report(report=report, pr_state=pr_state)


@mcp_tool
async def reconcile_fixes_links(
    body: str,
    base: str,
    head: str = "HEAD",
    repo_dir: str | None = None,
    acknowledge: list[int] | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Reconcile a PR body's Fixes:/Closes: links against its commits (GH-1241, GH-1777).

    Read-only: it reads ``git log base..head`` and changes nothing.

    Args:
        body: The PR body text.
        base: Base ref, e.g. ``origin/develop``.
        head: Head ref (default ``HEAD``).
        repo_dir: Absolute path of the checkout holding the PR branch.
            Defaults to ``cwd``; pass it when the branch lives in another
            worktree, or the range reads empty (GH-1464).
        acknowledge: Issue numbers deliberately linked without a commit of
            their own.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with ``ok``, ``linked``, ``delivered``, ``unbacked``,
        ``commits_read`` and ``summary``; ``hint`` when every link is
        unbacked by an empty range. ``ok: false`` blocks the merge.
    """
    from dev10x.coding import merge

    return await merge.reconcile_fixes_links(
        body=body,
        base=base,
        head=head,
        repo_dir=repo_dir,
        acknowledge=acknowledge,
    )


@mcp_tool
async def review_stamp_write(cwd: str | None = None) -> Result[dict]:
    """Record that a clean self-review covered the checked-out head (GH-1830).

    Call only after a ``dev10x:review`` round that found no defects. The
    stamp is built from local git state (HEAD, its tree, the ``origin``
    remote and the branch), never from caller-supplied SHAs; ``cwd``
    only selects the checkout. Where a repo's ``friction.yaml`` sets
    ``review_stamp: required``, DX019 compares it with the PR head
    before ``merge_pr``, ``pr_ready`` or ``request_review``. The stamp
    records the caller's word that a clean review ran; it does not
    prove one did, so it stops a session that forgot, not one that lies.

    Args:
        cwd: Effective working directory (GH-979) — the checkout that was
            reviewed.

    Returns:
        Dictionary with ``repo`` (owner/repo), ``branch``, ``head_sha``,
        ``tree_sha``, ``reviewed_at`` and ``path`` of the stamp store.
    """
    from dev10x.coding.merge.review_stamp import record_clean_review

    return await record_clean_review()
