"""GitHub MCP tool registrations (split from server_cli.py, GH-243/A6)."""

from __future__ import annotations

import functools

# Context is required at runtime: FastMCP evaluates tool annotations with
# eval_str=True to detect the injected context parameter (GH-342). The
# noqa keeps ruff from stripping it as a type-only import under
# `from __future__ import annotations`.
from mcp.server.fastmcp import Context  # noqa: F401

from dev10x import github as gh
from dev10x import subprocess_utils
from dev10x.domain.common.result import Result, to_wire
from dev10x.mcp._app import server


def github_tool(fn):
    """Wrap a GitHub handler with cwd binding + Result→dict unwrapping.

    The inner ``fn`` returns a ``Result``; this decorator enters
    ``use_cwd(kwargs["cwd"])`` and calls ``to_wire()`` at the MCP
    boundary. ``functools.wraps`` preserves the inner signature so
    FastMCP builds the correct tool schema.
    """

    @server.tool()
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        with subprocess_utils.use_cwd(kwargs.get("cwd")):
            result = await fn(*args, **kwargs)
        return to_wire(result)

    return wrapper


@github_tool
async def detect_tracker(ticket_id: str, cwd: str | None = None) -> Result[dict]:
    """Detect issue tracker type from a ticket ID.

    Args:
        ticket_id: Ticket identifier (e.g., GH-15, TEAM-133, JIRA-42)
        cwd: Effective working directory for git/gh subprocess calls.
            Pass the session's worktree path after EnterWorktree (GH-979).

    Returns:
        Dictionary with keys: tracker, ticket_id, ticket_number, fixes_url
    """
    return await gh.detect_tracker(ticket_id=ticket_id)


@github_tool
async def pr_detect(arg: str, cwd: str | None = None) -> Result[dict]:
    """Detect PR context from a PR number, URL, or branch name.

    Args:
        arg: PR number (#123), full URL, or branch name
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: pr_number, repo, branch, state, head_ref
    """
    return await gh.pr_detect(arg=arg)


@github_tool
async def pr_get(number: int, repo: str | None = None, cwd: str | None = None) -> Result[dict]:
    """Get GitHub PR details (GH-267).

    Symmetric to ``issue_get`` — closes the ``gh pr view`` permission-
    friction gap.

    Args:
        number: PR number.
        repo: Repository (owner/repo). If omitted, uses current repo.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: number, title, body, state, baseRefName,
        headRefName, merged, mergedAt, closedAt, labels, milestone,
        assignees, author, url.
    """
    return await gh.pr_get(number=number, repo=repo)


@github_tool
async def issue_get(number: int, repo: str | None = None, cwd: str | None = None) -> Result[dict]:
    """Get GitHub issue details.

    Args:
        number: Issue number
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: title, state, body, labels, linked_prs
    """
    return await gh.issue_get(number=number, repo=repo)


@github_tool
async def issue_comments(
    number: int, repo: str | None = None, cwd: str | None = None
) -> Result[dict]:
    """Get GitHub issue comments.

    Args:
        number: Issue number
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with key: comments (list of comment objects)
    """
    return await gh.issue_comments(number=number, repo=repo)


@github_tool
async def issue_create(
    title: str,
    body: str | None = None,
    labels: list[str] | None = None,
    milestone: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Create a GitHub issue.

    Args:
        title: Issue title
        body: Issue body text (optional)
        labels: List of label names to apply (optional)
        milestone: Milestone title to assign (optional)
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: number, title, url
    """
    return await gh.issue_create(
        title=title,
        body=body,
        labels=labels,
        milestone=milestone,
        repo=repo,
    )


@github_tool
async def pr_comments(
    action: str,
    pr_number: int | None = None,
    comment_id: int | str | None = None,
    comment_ids: list[str] | None = None,
    body: str | None = None,
    review_id: int | None = None,
    unresolved_only: bool = False,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Manage GitHub PR review comments and threads.

    Args:
        action: One of: list, get, reply, edit, resolve
        pr_number: PR number (required for list, reply)
        comment_id: Comment ID (required for get, reply, resolve single)
        comment_ids: List of GraphQL node_ids for batch resolve
        body: Comment body text (required for reply)
        review_id: When set with action="list", return only comments
            whose pull_request_review_id matches. Useful for filtering
            "the comments from review X" without overflowing the
            response budget.
        unresolved_only: When True with action="list", switch to a
            GraphQL reviewThreads query and return only the root
            comments of unresolved threads.
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with action results (comments list or operation status)
    """
    return await gh.pr_comments(
        action=action,
        pr_number=pr_number,
        comment_id=comment_id,
        comment_ids=comment_ids,
        body=body,
        review_id=review_id,
        unresolved_only=unresolved_only,
        repo=repo,
    )


@github_tool
async def pr_comment_reply(
    pr_number: int,
    comment_id: int,
    body: str,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Reply to a PR review comment thread.

    `body` is literal text — there is no `@file` / `--body-file`
    expansion; pass the reply content inline (GH-484).

    Args:
        pr_number: PR number
        comment_id: Root comment ID to reply to
        body: Reply text (supports markdown). Literal text.
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with reply details (id, body, created_at)
    """
    return await gh.pr_comment_reply(
        pr_number=pr_number,
        comment_id=comment_id,
        body=body,
        repo=repo,
    )


@github_tool
async def pr_issue_comment(
    pr_number: int,
    body: str,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Post a top-level issue-level comment on a PR.

    Wraps `gh api --method POST /repos/{owner}/{repo}/issues/{pr_number}/comments
    -f body=...`. Use this for replying to top-level bot findings posted via
    `gh pr comment` (claude[bot], hygiene-review) that surface through
    `check_top_level_comments` but have no review thread.

    For inline review-thread replies, use `pr_comment_reply` instead.

    `body` is literal text — there is no `@file` / `--body-file`
    expansion; pass the comment content inline (GH-484).

    Args:
        pr_number: PR number (treated as the parent issue for comment routing)
        body: Comment body (supports markdown). Literal text.
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with comment details (id, body, created_at) or error.
    """
    return await gh.pr_issue_comment(
        pr_number=pr_number,
        body=body,
        repo=repo,
    )


@github_tool
async def pr_review_comment_edit(
    comment_id: int,
    body: str,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Edit a PR inline review-thread comment body (GH-304).

    Uses PATCH against `/repos/{owner}/{repo}/pulls/comments/{id}`.
    Distinct from `issue_comment_edit` which targets the
    `/issues/comments/` endpoint (top-level issue + PR comments).
    Use this when editing inline review-thread comments — the ones
    tied to a file path + line number on a PR review (e.g., bot
    findings from claude-review, hygiene-review).

    Args:
        comment_id: Numeric ID of the review-thread comment to edit
            (from the /comments/<id> URL fragment).
        body: New body text (full replacement, not a delta).
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: id, body, html_url.
    """
    return await gh.pr_comment_edit(
        comment_id=comment_id,
        body=body,
        repo=repo,
    )


@github_tool
async def minimize_comments(
    node_ids: list[str],
    classifier: str = "OUTDATED",
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Minimize (hide) one or more PR review comments via batched GraphQL.

    Replaces a per-comment `gh api graphql -f query=@file` loop with a
    single GraphQL mutation that aliases `minimizeComment` calls — one
    request, no loop.

    Args:
        node_ids: GraphQL node IDs of the comments to minimize (PRRC_...)
        classifier: Reason category. One of: ABUSE, DUPLICATE,
            OFF_TOPIC, OUTDATED (default), RESOLVED, SPAM
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with batched mutation results keyed as m0, m1, ...
        each containing minimizedComment { isMinimized, minimizedReason }
    """
    return await gh.minimize_comments(
        node_ids=node_ids,
        classifier=classifier,
        repo=repo,
    )


@github_tool
async def request_review(
    pr_number: int,
    reviewers: list[str],
    team: bool | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Request review on a GitHub PR from users or teams.

    Args:
        pr_number: PR number
        reviewers: List of reviewer usernames or team names
        team: Whether reviewers are teams (vs users)
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: requested_reviewers or requested_teams
    """
    return await gh.request_review(
        pr_number=pr_number,
        reviewers=reviewers,
        team=team,
        repo=repo,
    )


@github_tool
async def detect_base_branch(
    base: str | None = None,
    force: bool = False,
    cwd: str | None = None,
) -> Result[dict]:
    """Detect the correct base branch for PRs in the current repository.

    Prefers develop/development, falls back to main/master/trunk.

    Args:
        base: Explicit base branch override
        force: Skip warning when overriding to non-development base
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: base_branch (str), has_develop (bool)
    """
    return await gh.detect_base_branch(base=base, force=force)


@github_tool
async def verify_pr_state(force: bool = False, cwd: str | None = None) -> Result[dict]:
    """Verify branch state before creating a PR.

    Args:
        force: Allow targeting a non-development base branch
        cwd: Effective working directory (GH-979). Pass the worktree
            path after EnterWorktree so branch detection reads the
            worktree's HEAD, not the main repo's.

    Returns:
        Dictionary with keys: branch_name, issue, base_branch
    """
    return await gh.verify_pr_state(force=force)


@github_tool
async def pre_pr_checks(base_branch: str | None = None, cwd: str | None = None) -> Result[dict]:
    """Run pre-PR quality checks (ruff, mypy, pytest).

    Args:
        base_branch: Base branch for diff comparison. Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    return await gh.pre_pr_checks(base_branch=base_branch)


@server.tool()
async def create_pr(
    title: str,
    job_story: str,
    issue_id: str,
    fixes_url: str | None = None,
    base_branch: str | None = None,
    closes: list[int] | None = None,
    draft: bool = True,
    head_repo: str | None = None,
    cwd: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Create a PR with two-pass body generation.

    Args:
        title: PR title
        job_story: JTBD Job Story for the PR body
        issue_id: Ticket ID extracted from branch name
        fixes_url: Issue URL for the Fixes: line
        base_branch: Base branch. Auto-detected if omitted.
        closes: Issue numbers to close on merge — emitted as
            `Closes #N` lines (GH-186). Use for milestone-bundle
            PRs that ship multiple issues.
        draft: Create as draft (default True). Pass False in
            solo-maintainer mode so the PR is immediately
            ready-for-review (GH-184).
        head_repo: Fork owner for a cross-fork PR (GH-473). When set,
            the head branch is pushed to that owner's remote and the
            PR opens with `--head <head_repo>:<branch>` against the
            upstream base. Omit for same-repo PRs.
        cwd: Effective working directory (GH-979). Pass the worktree
            path after EnterWorktree so the PR is created from the
            worktree's branch, not the main repo's.
        ctx: FastMCP context injected automatically — do not pass (GH-342).

    Returns:
        Dictionary with keys: pr_number (int), url (str)
    """
    from dev10x.subprocess_utils import use_cwd

    if ctx is not None:
        await ctx.report_progress(progress=0, total=100, message=f"Creating PR: {title}")
        await ctx.info(f"create_pr: opening PR for {issue_id} (draft={draft})")

    with use_cwd(cwd):
        result = to_wire(
            await gh.create_pr(
                title=title,
                job_story=job_story,
                issue_id=issue_id,
                fixes_url=fixes_url,
                base_branch=base_branch,
                closes=closes,
                draft=draft,
                head_repo=head_repo,
            )
        )

    if ctx is not None:
        if "error" in result:
            await ctx.report_progress(
                progress=100, total=100, message=f"PR creation failed: {result['error']}"
            )
            await ctx.log(level="error", message=f"create_pr: {result['error']}")
        else:
            url = result.get("url", "")
            await ctx.report_progress(progress=100, total=100, message=f"PR created: {url}")
            await ctx.info(f"create_pr: PR #{result.get('pr_number')} ready at {url}")

    return result


@github_tool
async def update_pr(
    pr_number: int,
    body: str | None = None,
    title: str | None = None,
    base_branch: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Update an existing PR's body, title, or base branch.

    Mirrors create_pr for in-place updates after force-push or scope
    changes. Wraps `gh api -X PATCH repos/{repo}/pulls/{N}`.

    Args:
        pr_number: PR number to update
        body: New PR body (markdown). Omit to leave unchanged.
        title: New PR title. Omit to leave unchanged.
        base_branch: New base branch (re-target). Omit to leave unchanged.
        repo: Repository (owner/repo). Auto-detected if omitted.

    At least one of body, title, or base_branch is required.

    `cwd` selects the effective working directory (GH-979).

    Returns:
        Dictionary with keys: pr_number (int), url (str)
    """
    return await gh.update_pr(
        pr_number=pr_number,
        body=body,
        title=title,
        base_branch=base_branch,
        repo=repo,
    )


@github_tool
async def merge_pr(
    pr_number: int,
    strategy: str = "rebase",
    delete_branch: bool = True,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Merge a pull request via ``gh pr merge`` (GH-232).

    Symmetric to ``create_pr``/``update_pr``. Provides a structured
    MCP entry point for the merge so ``Dev10x:gh-pr-merge`` Step 5
    can ship the merge without hitting the PreToolUse hook that
    blocks raw ``gh pr merge`` Bash invocations.

    The skill must still run all 8 pre-merge checks before calling
    this tool — the hook block was the only reason the documented
    Step 5 was unreachable; the checks themselves remain mandatory.

    Args:
        pr_number: PR number to merge.
        strategy: One of ``rebase`` (default), ``squash``, ``merge``.
            Resolved by the skill from
            ``<Dev10x config>/settings-pr-merge.yaml`` — see
            ``references/config-resolution.md`` for the per-platform
            resolution table.
        delete_branch: Pass ``--delete-branch`` to ``gh pr merge``
            when True (default).
        repo: Repository (owner/repo). Auto-detected if omitted.
            Always passed as ``--repo`` to ``gh pr merge`` for
            worktree safety (GH-773).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: pr_number (int), url (str),
        strategy (str), branch_deleted (bool), repo (str).
    """
    return await gh.merge_pr(
        pr_number=pr_number,
        strategy=strategy,
        delete_branch=delete_branch,
        repo=repo,
    )


@github_tool
async def issue_edit(
    number: int,
    title: str | None = None,
    body: str | None = None,
    milestone: str | None = None,
    labels: list[str] | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Edit a GitHub issue's title, body, milestone, or labels (GH-220).

    Wraps `gh issue edit`. Accepts partial updates — pass only the
    fields to change.

    Args:
        number: Issue number to edit.
        title: New title (optional).
        body: New body text (optional).
        milestone: Milestone title to assign (optional).
        labels: Replacement label list (optional).
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: number, url
    """
    return await gh.issue_edit(
        number=number,
        title=title,
        body=body,
        milestone=milestone,
        labels=labels,
        repo=repo,
    )


@github_tool
async def issue_close(
    number: int,
    reason: str = "completed",
    comment: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Close a GitHub issue (GH-268).

    Wraps `gh issue close N --reason <reason>` plus an optional
    `--comment` body. Closes the `gh issue close` permission-friction
    gap so skills like work-on can finalise epic closure.

    Args:
        number: Issue number to close.
        reason: "completed" (default) or "not_planned".
        comment: Optional final closing comment (Markdown supported).
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: number, state ("closed"), url.
    """
    return await gh.issue_close(
        number=number,
        reason=reason,
        comment=comment,
        repo=repo,
    )


@github_tool
async def issue_reopen(
    number: int,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Reopen a closed GitHub issue (GH-268).

    Wraps `gh issue reopen N`. Symmetric to `issue_close`.

    Args:
        number: Issue number to reopen.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: number, state ("open"), url.
    """
    return await gh.issue_reopen(number=number, repo=repo)


@github_tool
async def issue_comment(
    number: int,
    body: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
    body_file: str | None = None,
) -> Result[dict]:
    """Post a Markdown comment on a GitHub issue (GH-220).

    Wraps `gh issue comment N --body-file <tmp>` so callers don't
    need to manage heredoc/quoting at the Bash boundary.

    `body` is literal text — there is no `@file` / `--body-file`
    expansion (passing `body="@/path.md"` posts the literal path string).
    To post the contents of a file, pass `body_file` instead (GH-484).

    Args:
        number: Issue number to comment on.
        body: Comment body (Markdown supported). Literal text.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).
        body_file: Path to a file whose contents become the body.
            Mutually exclusive with `body`.

    Returns:
        Dictionary with key: url (the comment permalink).
    """
    return await gh.issue_comment(
        number=number,
        body=body,
        repo=repo,
        body_file=body_file,
    )


@github_tool
async def issue_comment_edit(
    comment_id: int,
    body: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
    body_file: str | None = None,
) -> Result[dict]:
    """Edit an existing GitHub issue or PR comment body (GH-283).

    Symmetric to `issue_comment` (POST) but uses PATCH against
    `/repos/{owner}/{repo}/issues/comments/{id}`. Works on issue
    comments and PR issue-level comments.

    `body` is literal text — there is no `@file` / `--body-file`
    expansion. To replace with the contents of a file, pass `body_file`
    instead (GH-484).

    Args:
        comment_id: Numeric ID of the comment to edit (from
            /comments/<id> URL fragment).
        body: New body text (full replacement; not a delta). Literal text.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).
        body_file: Path to a file whose contents become the new body.
            Mutually exclusive with `body`.

    Returns:
        Dictionary with keys: id, body, html_url.
    """
    return await gh.issue_comment_edit(
        comment_id=comment_id,
        body=body,
        repo=repo,
        body_file=body_file,
    )


@github_tool
async def issue_comment_delete(
    comment_id: int,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Delete a GitHub issue or PR comment (GH-283).

    Uses DELETE against `/repos/{owner}/{repo}/issues/comments/{id}`.
    Works on issue comments and PR issue-level comments.

    Args:
        comment_id: Numeric ID of the comment to delete.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: deleted (bool), comment_id (int).
    """
    return await gh.issue_comment_delete(
        comment_id=comment_id,
        repo=repo,
    )


@github_tool
async def issue_list(
    repo: str | None = None,
    state: str = "open",
    milestone: str | None = None,
    labels: list[str] | None = None,
    limit: int = 30,
    search: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """List GitHub issues, optionally filtered (GH-220).

    Wraps `gh issue list ... --json
    number,title,labels,milestone,state,url`.

    Args:
        repo: Repository (owner/repo). Auto-detected if omitted.
        state: Filter by state: open (default), closed, all.
        milestone: Filter by milestone title or number.
        labels: Filter by labels (matches ALL labels).
        limit: Max results (default 30).
        search: Free-text search filter (passed via --search).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with key: issues (list of issue dicts).
    """
    return await gh.issue_list(
        repo=repo,
        state=state,
        milestone=milestone,
        labels=labels,
        limit=limit,
        search=search,
    )


@github_tool
async def milestone_create(
    title: str,
    description: str | None = None,
    due_on: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Create a GitHub milestone (GH-220).

    Wraps `gh api repos/{r}/milestones --method POST`. Mirrors the
    shape of the existing milestone_close tool.

    Args:
        title: Milestone title (required, must be unique within repo).
        description: Optional milestone description.
        due_on: Optional ISO-8601 timestamp for the due date.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: number, title, url.
    """
    return await gh.milestone_create(
        title=title,
        description=description,
        due_on=due_on,
        repo=repo,
    )


@github_tool
async def milestones_bulk_create(
    milestones: list[dict],
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Create multiple GitHub milestones in one call (GH-222).

    Iterates `milestone_create` per entry and collects per-entry
    successes and failures.

    Args:
        milestones: List of dicts; each entry: {title, description?, due_on?}.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: created (list), failed (list).
    """
    return await gh.milestones_bulk_create(
        milestones=milestones,
        repo=repo,
    )


@github_tool
async def issues_bulk_create(
    issues: list[dict],
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Create multiple GitHub issues in one call (GH-222).

    Iterates `issue_create` per entry and collects per-entry
    successes and failures.

    Args:
        issues: List of dicts; each entry: {title, body?, labels?, milestone?}.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: created (list), failed (list).
    """
    return await gh.issues_bulk_create(
        issues=issues,
        repo=repo,
    )


@github_tool
async def issues_bulk_edit(
    edits: list[dict],
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Edit multiple GitHub issues in one call (GH-222).

    Iterates `issue_edit` per entry and collects per-entry
    successes and failures.

    Args:
        edits: List of dicts; each entry requires `number` and at least
            one of `title`, `body`, `milestone`, `labels`.
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: edited (list), failed (list).
    """
    return await gh.issues_bulk_edit(
        edits=edits,
        repo=repo,
    )


@github_tool
async def milestone_close(
    number: int,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Close a GitHub milestone via REST API (GH-187).

    Use from gh-pr-monitor after all milestone issues are closed.
    Wraps `gh api -X PATCH repos/{repo}/milestones/{N} -f state=closed`,
    which the plugin permission manifest blocks at the Bash layer.

    Args:
        number: Milestone number to close
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: number (int), state ("closed"), url (str)
    """
    return await gh.milestone_close(
        number=number,
        repo=repo,
    )


@github_tool
async def generate_commit_list(
    pr_number: int,
    base_branch: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Generate a linked commit list for a PR body.

    Args:
        pr_number: PR number for commit links
        base_branch: Base branch. Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with key: commit_list (str)
    """
    return await gh.generate_commit_list(pr_number=pr_number, base_branch=base_branch)


@github_tool
async def post_summary_comment(
    issue_id: str,
    summary_text: str,
    cwd: str | None = None,
) -> Result[dict]:
    """Post summary + checklist as first PR comment.

    Args:
        issue_id: Ticket ID for checklist substitution
        summary_text: Markdown bullet points (one per line)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    return await gh.post_summary_comment(issue_id=issue_id, summary_text=summary_text)


@github_tool
async def pr_notify(
    pr_number: int,
    repo: str,
    action: str = "prepare",
    channel: str | None = None,
    message: str | None = None,
    message_file: str | None = None,
    reviewer: str | None = None,
    skip_slack: bool = False,
    skip_reviewers: bool = False,
    skip_checklist: bool = False,
    cwd: str | None = None,
) -> Result[dict]:
    """PR notification helper for review requests.

    Args:
        pr_number: PR number
        repo: GitHub repo (owner/name)
        action: "prepare" or "send"
        channel: Slack channel ID (send only)
        message: Notification message text (send only)
        message_file: Path to message file (send only)
        reviewer: GitHub reviewer to assign (send only)
        skip_slack: Skip Slack notification (send only)
        skip_reviewers: Skip reviewer assignment (send only)
        skip_checklist: Skip checklist update (send only)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with PR info (prepare) or operation results (send)
    """
    return await gh.pr_notify(
        pr_number=pr_number,
        repo=repo,
        action=action,
        channel=channel,
        message=message,
        message_file=message_file,
        reviewer=reviewer,
        skip_slack=skip_slack,
        skip_reviewers=skip_reviewers,
        skip_checklist=skip_checklist,
    )


@github_tool
async def resolve_review_thread(
    thread_ids: list[str] | None = None,
    comment_ids: list[str] | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Resolve GitHub PR review threads by thread ID or comment node ID.

    Accepts either direct thread IDs (PRRT_...) for immediate resolution,
    or comment node IDs that are looked up to find their parent thread first.

    Args:
        thread_ids: List of PRRT_ thread IDs to resolve directly
        comment_ids: List of GraphQL comment node IDs (thread lookup needed)
        repo: Repository (owner/repo). Required when using comment_ids.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with GraphQL mutation results per resolved thread
    """
    return await gh.resolve_review_thread(
        thread_ids=thread_ids,
        comment_ids=comment_ids,
        repo=repo,
    )


@github_tool
async def check_top_level_comments(
    pr_number: int,
    repo: str,
    cwd: str | None = None,
) -> Result[dict]:
    """Check for unaddressed automated review comments on a PR.

    Args:
        pr_number: PR number to scan
        repo: Repository in owner/repo format
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: findings (list), count (int)
    """
    return await gh.check_top_level_comments(pr_number=pr_number, repo=repo)


@github_tool
async def unresolved_threads(
    repo: str,
    limit: int = 200,
    cwd: str | None = None,
) -> Result[dict]:
    """Scan merged PRs for unresolved review comment threads.

    Args:
        repo: Repository in owner/repo format
        limit: Max PRs to scan (default 200)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: prs (list), count (int)
    """
    return await gh.unresolved_threads(repo=repo, limit=limit)


@github_tool
async def cluster_review_comments(
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
    cwd: str | None = None,
) -> Result[dict]:
    """Cluster & score PR review-comment patterns (GH-346).

    Fetches inline review comments from recent merged PRs, groups them
    into recurring candidate patterns, and ranks each by frequency so
    the top-N findings can feed a candidate-rules report (GH-347).

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned per repo (default 50).
        top_n: Number of top patterns to return (default 20).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: patterns (list), summary (dict); or error.
    """
    from dev10x.github import review_patterns

    return await review_patterns.cluster_review_comments(
        repos=repos,
        limit=limit,
        top_n=top_n,
    )


@github_tool
async def candidate_rules_report(
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
    cwd: str | None = None,
) -> Result[dict]:
    """Produce a read-only candidate-rules report (GH-347).

    Mines recurring review-comment patterns via ``cluster_review_comments``
    (GH-346) and renders them into a human-readable Markdown memo. This is
    a read-only visibility step — it surfaces candidate patterns for human
    review and does NOT generate, write, or apply any permission rule.

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned per repo (default 50).
        top_n: Number of top patterns to include (default 20).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: report (str), patterns (list), summary
        (dict); or error.
    """
    from dev10x.github import candidate_rules

    return await candidate_rules.candidate_rules_report(
        repos=repos,
        limit=limit,
        top_n=top_n,
    )


@github_tool
async def validate_candidate_patterns(
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
    diff_limit: int = 20,
    min_frequency: int = 2,
    max_fp_rate: float = 0.5,
    cwd: str | None = None,
) -> Result[dict]:
    """Validate candidate review-comment patterns against recent diffs (GH-348).

    Mines recurring review-comment patterns via ``cluster_review_comments``
    (GH-346), fetches recent merged-PR diffs, and estimates a heuristic
    false-positive rate for each pattern so the validated subset can feed
    reference-rule authoring (GH-349). The false-positive rate is a
    heuristic estimate, not a measured ground truth.

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned for review comments (default 50).
        top_n: Number of top candidate patterns to validate (default 20).
        diff_limit: Max recent merged PRs sampled for diff matching
            (default 20).
        min_frequency: Minimum reviewer frequency for a validated pattern
            (default 2).
        max_fp_rate: Maximum estimated false-positive rate for a
            validated pattern (default 0.5).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: validated (list), summary (dict); or error.
    """
    from dev10x.github import pattern_validation

    return await pattern_validation.validate_candidate_patterns(
        repos=repos,
        limit=limit,
        top_n=top_n,
        diff_limit=diff_limit,
        min_frequency=min_frequency,
        max_fp_rate=max_fp_rate,
    )


@github_tool
async def author_reference_rules(
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
    diff_limit: int = 20,
    min_frequency: int = 2,
    max_fp_rate: float = 0.5,
    cwd: str | None = None,
) -> Result[dict]:
    """Author reference-rule docs from validated review patterns (GH-349).

    Validates candidate patterns (GH-348), then renders one
    reference-rule Markdown doc per validated pattern plus an INDEX-style
    routing fragment. Dry run: no files are written and no routing table
    is edited — the docs and fragment are returned for human review.

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned for review comments (default 50).
        top_n: Number of top candidate patterns to consider (default 20).
        diff_limit: Max recent merged PRs sampled for diff matching
            (default 20).
        min_frequency: Minimum reviewer frequency for a validated pattern
            (default 2).
        max_fp_rate: Maximum estimated false-positive rate for a
            validated pattern (default 0.5).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: rules (list), routing_fragment (str),
        summary (dict); or error.
    """
    from dev10x.github import rule_authoring

    return await rule_authoring.author_reference_rules(
        repos=repos,
        limit=limit,
        top_n=top_n,
        diff_limit=diff_limit,
        min_frequency=min_frequency,
        max_fp_rate=max_fp_rate,
    )


@github_tool
async def rule_confidence_report(
    store_path: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Rank review rules by feedback-weighted confidence (GH-350).

    Reads the catch/false-positive feedback store and ranks rules by a
    95% Wilson-score lower bound on precision, so high-precision rules
    surface first and noisy ones sink.

    Args:
        store_path: Feedback JSON store. Defaults to the Dev10x config
            home when omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: ranked (list), summary (dict).
    """
    from dev10x.github import rule_confidence

    return await rule_confidence.rule_confidence_report(store_path=store_path)


@github_tool
async def record_rule_feedback(
    rule_id: str,
    outcome: str,
    store_path: str | None = None,
    cwd: str | None = None,
) -> Result[dict]:
    """Record one catch or false-positive for a review rule (GH-350).

    Args:
        rule_id: Identifier of the rule that fired.
        outcome: ``"catch"`` (real issue) or ``"false_positive"``.
        store_path: Feedback JSON store. Defaults to the Dev10x config
            home when omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with key: feedback (dict); or error on bad outcome.
    """
    from dev10x.github import rule_confidence

    return await rule_confidence.record_rule_feedback(
        rule_id=rule_id,
        outcome=outcome,
        store_path=store_path,
    )
