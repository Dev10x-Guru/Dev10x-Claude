"""MCP server registration for the Dev10x CLI server.

All @server.tool() registrations live here so servers/cli_server.py
becomes a thin 3-line uv shim. Tool handlers use lazy imports to
defer domain module loading until each tool is called.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP(name="Dev10x-cli")

# GH-979: every CWD-sensitive tool accepts an optional `cwd` argument.
# Skills must pass the session's effective working directory (e.g. the
# worktree path after EnterWorktree) so subprocess_utils binds it via
# the `_effective_cwd` ContextVar before any git/gh subprocess fires.
# When `cwd` is None, behavior is unchanged from pre-GH-979 (subprocess
# inherits the MCP server's startup CWD).


# ── GitHub tools ────────────────────────────────────────────────


@server.tool()
async def detect_tracker(ticket_id: str, cwd: str | None = None) -> dict:
    """Detect issue tracker type from a ticket ID.

    Args:
        ticket_id: Ticket identifier (e.g., GH-15, TEAM-133, JIRA-42)
        cwd: Effective working directory for git/gh subprocess calls.
            Pass the session's worktree path after EnterWorktree (GH-979).

    Returns:
        Dictionary with keys: tracker, ticket_id, ticket_number, fixes_url
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.detect_tracker(ticket_id=ticket_id)).to_dict()


@server.tool()
async def pr_detect(arg: str, cwd: str | None = None) -> dict:
    """Detect PR context from a PR number, URL, or branch name.

    Args:
        arg: PR number (#123), full URL, or branch name
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: pr_number, repo, branch, state, head_ref
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.pr_detect(arg=arg)).to_dict()


@server.tool()
async def issue_get(number: int, repo: str | None = None, cwd: str | None = None) -> dict:
    """Get GitHub issue details.

    Args:
        number: Issue number
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: title, state, body, labels, linked_prs
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.issue_get(number=number, repo=repo)).to_dict()


@server.tool()
async def issue_comments(number: int, repo: str | None = None, cwd: str | None = None) -> dict:
    """Get GitHub issue comments.

    Args:
        number: Issue number
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with key: comments (list of comment objects)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.issue_comments(number=number, repo=repo)).to_dict()


@server.tool()
async def issue_create(
    title: str,
    body: str | None = None,
    labels: list[str] | None = None,
    milestone: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.issue_create(
                title=title,
                body=body,
                labels=labels,
                milestone=milestone,
                repo=repo,
            )
        ).to_dict()


@server.tool()
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
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.pr_comments(
                action=action,
                pr_number=pr_number,
                comment_id=comment_id,
                comment_ids=comment_ids,
                body=body,
                review_id=review_id,
                unresolved_only=unresolved_only,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def pr_comment_reply(
    pr_number: int,
    comment_id: int,
    body: str,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Reply to a PR review comment thread.

    Args:
        pr_number: PR number
        comment_id: Root comment ID to reply to
        body: Reply text (supports markdown)
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with reply details (id, body, created_at)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.pr_comment_reply(
                pr_number=pr_number,
                comment_id=comment_id,
                body=body,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def pr_issue_comment(
    pr_number: int,
    body: str,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Post a top-level issue-level comment on a PR.

    Wraps `gh api --method POST /repos/{owner}/{repo}/issues/{pr_number}/comments
    -f body=...`. Use this for replying to top-level bot findings posted via
    `gh pr comment` (claude[bot], hygiene-review) that surface through
    `check_top_level_comments` but have no review thread.

    For inline review-thread replies, use `pr_comment_reply` instead.

    Args:
        pr_number: PR number (treated as the parent issue for comment routing)
        body: Comment body (supports markdown)
        repo: Repository (owner/repo). If omitted, uses current repo
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with comment details (id, body, created_at) or error.
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.pr_issue_comment(
                pr_number=pr_number,
                body=body,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def minimize_comments(
    node_ids: list[str],
    classifier: str = "OUTDATED",
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.minimize_comments(
                node_ids=node_ids,
                classifier=classifier,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def request_review(
    pr_number: int,
    reviewers: list[str],
    team: bool | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.request_review(
                pr_number=pr_number,
                reviewers=reviewers,
                team=team,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def detect_base_branch(
    base: str | None = None,
    force: bool = False,
    cwd: str | None = None,
) -> dict:
    """Detect the correct base branch for PRs in the current repository.

    Prefers develop/development, falls back to main/master/trunk.

    Args:
        base: Explicit base branch override
        force: Skip warning when overriding to non-development base
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: base_branch (str), has_develop (bool)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.detect_base_branch(base=base, force=force)).to_dict()


@server.tool()
async def verify_pr_state(force: bool = False, cwd: str | None = None) -> dict:
    """Verify branch state before creating a PR.

    Args:
        force: Allow targeting a non-development base branch
        cwd: Effective working directory (GH-979). Pass the worktree
            path after EnterWorktree so branch detection reads the
            worktree's HEAD, not the main repo's.

    Returns:
        Dictionary with keys: branch_name, issue, base_branch
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.verify_pr_state(force=force)).to_dict()


@server.tool()
async def pre_pr_checks(base_branch: str | None = None, cwd: str | None = None) -> dict:
    """Run pre-PR quality checks (ruff, mypy, pytest).

    Args:
        base_branch: Base branch for diff comparison. Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.pre_pr_checks(base_branch=base_branch)).to_dict()


@server.tool()
async def create_pr(
    title: str,
    job_story: str,
    issue_id: str,
    fixes_url: str | None = None,
    base_branch: str | None = None,
    closes: list[int] | None = None,
    draft: bool = True,
    cwd: str | None = None,
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
        cwd: Effective working directory (GH-979). Pass the worktree
            path after EnterWorktree so the PR is created from the
            worktree's branch, not the main repo's.

    Returns:
        Dictionary with keys: pr_number (int), url (str)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.create_pr(
                title=title,
                job_story=job_story,
                issue_id=issue_id,
                fixes_url=fixes_url,
                base_branch=base_branch,
                closes=closes,
                draft=draft,
            )
        ).to_dict()


@server.tool()
async def update_pr(
    pr_number: int,
    body: str | None = None,
    title: str | None = None,
    base_branch: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.update_pr(
                pr_number=pr_number,
                body=body,
                title=title,
                base_branch=base_branch,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def issue_edit(
    number: int,
    title: str | None = None,
    body: str | None = None,
    milestone: str | None = None,
    labels: list[str] | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.issue_edit(
                number=number,
                title=title,
                body=body,
                milestone=milestone,
                labels=labels,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def issue_comment(
    number: int,
    body: str,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Post a Markdown comment on a GitHub issue (GH-220).

    Wraps `gh issue comment N --body-file <tmp>` so callers don't
    need to manage heredoc/quoting at the Bash boundary.

    Args:
        number: Issue number to comment on.
        body: Comment body (Markdown supported).
        repo: Repository (owner/repo). Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with key: url (the comment permalink).
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.issue_comment(
                number=number,
                body=body,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def issue_list(
    repo: str | None = None,
    state: str = "open",
    milestone: str | None = None,
    labels: list[str] | None = None,
    limit: int = 30,
    search: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.issue_list(
                repo=repo,
                state=state,
                milestone=milestone,
                labels=labels,
                limit=limit,
                search=search,
            )
        ).to_dict()


@server.tool()
async def milestone_create(
    title: str,
    description: str | None = None,
    due_on: str | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.milestone_create(
                title=title,
                description=description,
                due_on=due_on,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def milestones_bulk_create(
    milestones: list[dict],
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.milestones_bulk_create(
                milestones=milestones,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def issues_bulk_create(
    issues: list[dict],
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.issues_bulk_create(
                issues=issues,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def issues_bulk_edit(
    edits: list[dict],
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.issues_bulk_edit(
                edits=edits,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def slack_thread_is_forward(
    parent_body: str,
    reply_count: int,
) -> dict:
    """Detect whether a Slack thread is likely a forward / cross-post (GH-218).

    Pure heuristic over an already-fetched thread payload. The caller
    fetches the thread via `mcp__claude_ai_Slack__slack_read_thread`
    and passes the parent message body + reply count here.

    Signals:
    - short_body: parent body word count below threshold (~30 words)
    - zero_replies: thread has no replies
    - external_link OR forwarding_language: parent references an
      external URL or uses forwarding phrasing (fwd, FYI, sharing, ...)

    Confidence:
    - high: all 3 signals present
    - medium: exactly 2 signals present
    - low: 0 or 1 signals present

    Args:
        parent_body: The parent message text from the Slack thread.
        reply_count: Number of replies on the thread.

    Returns:
        Dictionary with keys: is_forward (bool), confidence (str),
        signals (list[str]), upstream_hints (list[str]).
    """
    from dev10x.github import slack as slack_helper

    return (
        await slack_helper.slack_thread_is_forward(
            parent_body=parent_body,
            reply_count=reply_count,
        )
    ).to_dict()


@server.tool()
async def milestone_close(
    number: int,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.milestone_close(
                number=number,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def generate_commit_list(
    pr_number: int,
    base_branch: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Generate a linked commit list for a PR body.

    Args:
        pr_number: PR number for commit links
        base_branch: Base branch. Auto-detected if omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with key: commit_list (str)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.generate_commit_list(pr_number=pr_number, base_branch=base_branch)
        ).to_dict()


@server.tool()
async def post_summary_comment(
    issue_id: str,
    summary_text: str,
    cwd: str | None = None,
) -> dict:
    """Post summary + checklist as first PR comment.

    Args:
        issue_id: Ticket ID for checklist substitution
        summary_text: Markdown bullet points (one per line)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.post_summary_comment(issue_id=issue_id, summary_text=summary_text)
        ).to_dict()


@server.tool()
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
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.pr_notify(
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
        ).to_dict()


# ── Git tools ───────────────────────────────────────────────────


@server.tool()
async def push_safe(
    args: list[str],
    protected_branches: list[str] | None = None,
    cwd: str | None = None,
) -> dict:
    """Safely push git branches with protection for main/develop.

    Args:
        args: Arguments to pass to git push (e.g., ["origin", "branch-name"])
        protected_branches: List of branch names to protect (default: main, develop)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), branch, remote, blocked_reason (if blocked)

    Success semantics (GH-152):
        An empty dict `{}` IS a successful push — the underlying
        `git push` script may emit no key/value output on a clean
        fast-forward. Callers MUST NOT interpret `{}` as failure
        and MUST NOT fall back to raw `git push` (which is
        hook-blocked). To verify the remote actually received the
        push, run `git ls-remote --heads origin <branch>` and
        compare against the local HEAD SHA. A real failure
        returns `{"error": "<message>"}` — branch on the `error`
        key, not on emptiness.
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await git_tools.push_safe(args=args, protected_branches=protected_branches)
        ).to_dict()


@server.tool()
async def rebase_groom(seq_path: str, base_ref: str, cwd: str | None = None) -> dict:
    """Rebase and groom commits using an interactive sequence file.

    Args:
        seq_path: Path to git rebase sequence file
        base_ref: Base ref to rebase onto (e.g., develop, main)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), commits_rewritten (int)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.rebase_groom(seq_path=seq_path, base_ref=base_ref)).to_dict()


@server.tool()
async def create_worktree(
    branch: str,
    base: str | None = None,
    path: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Create a new git worktree.

    Args:
        branch: Branch name for the worktree
        base: Base ref to create from (default: develop)
        path: Worktree path (default: ../.worktrees/{project}-NN)
        cwd: Effective working directory (GH-979). The new worktree
            is added relative to this repo.

    Returns:
        Dictionary with keys: worktree_path, branch, created (bool)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.create_worktree(branch=branch, base=base, path=path)).to_dict()


@server.tool()
async def mass_rewrite(config_path: str, cwd: str | None = None) -> dict:
    """Rewrite multiple commit messages in one unattended rebase pass.

    Args:
        config_path: Path to JSON config file with rewrite instructions.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str), error (str if failed)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.mass_rewrite(config_path=config_path)).to_dict()


@server.tool()
async def start_split_rebase(
    commit_hash: str,
    base_branch: str = "develop",
    cwd: str | None = None,
) -> dict:
    """Start an interactive rebase to split a commit.

    Args:
        commit_hash: The commit hash to split
        base_branch: Base branch for the rebase (default: develop)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str), error (str if failed)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await git_tools.start_split_rebase(commit_hash=commit_hash, base_branch=base_branch)
        ).to_dict()


@server.tool()
async def next_worktree_name(base_dir: str | None = None, cwd: str | None = None) -> dict:
    """Calculate the next available worktree path.

    Args:
        base_dir: Override worktrees parent directory (default: ../.worktrees)
        cwd: Effective working directory (GH-979). The .worktrees parent
            is computed relative to this repo when base_dir is omitted.

    Returns:
        Dictionary with keys: path (str)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.next_worktree_name(base_dir=base_dir)).to_dict()


@server.tool()
async def setup_aliases() -> dict:
    """Set up global git aliases for branch comparison operations.

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import git as git_tools

    return (await git_tools.setup_aliases()).to_dict()


# ── Utility tools ───────────────────────────────────────────────


@server.tool()
async def mktmp(
    namespace: str,
    prefix: str,
    ext: str = "",
    directory: bool = False,
    create: bool = False,
) -> dict:
    """Generate a unique temp path under /tmp/Dev10x/<namespace>/.

    Files: returns a path WITHOUT creating the file by default so
    callers using the Write tool don't trigger its overwrite gate
    (GH-39). Pass create=True for legacy pre-created behavior.
    Directories: always created (the directory is the resource).

    Args:
        namespace: Subdirectory under /tmp/Dev10x/ (e.g., "git", "skill-audit")
        prefix: Filename prefix (e.g., "commit-msg", "pr-review")
        ext: File extension including dot (e.g., ".txt", ".json"). Ignored for directories.
        directory: If True, create a directory instead of a file.
        create: If True (and directory=False), pre-create an empty file.
            Default False — Write callers should write fresh.

    Returns:
        Dictionary with key: path (str) — the temp file/directory path
    """
    from dev10x import utilities as util

    return (
        await util.mktmp(
            namespace=namespace,
            prefix=prefix,
            ext=ext,
            directory=directory,
            create=create,
        )
    ).to_dict()


# ── Plan/Task tools ────────────────────────────────────────────


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
        return (await plan_tools.set_context(args=args)).to_dict()


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
        return (await plan_tools.json_summary()).to_dict()


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
        return (await plan_tools.archive()).to_dict()


# ── GitHub review tools ────────────────────────────────────────


@server.tool()
async def resolve_review_thread(
    thread_ids: list[str] | None = None,
    comment_ids: list[str] | None = None,
    repo: str | None = None,
    cwd: str | None = None,
) -> dict:
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
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await gh.resolve_review_thread(
                thread_ids=thread_ids,
                comment_ids=comment_ids,
                repo=repo,
            )
        ).to_dict()


@server.tool()
async def check_top_level_comments(
    pr_number: int,
    repo: str,
    cwd: str | None = None,
) -> dict:
    """Check for unaddressed automated review comments on a PR.

    Args:
        pr_number: PR number to scan
        repo: Repository in owner/repo format
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: findings (list), count (int)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.check_top_level_comments(pr_number=pr_number, repo=repo)).to_dict()


@server.tool()
async def unresolved_threads(
    repo: str,
    limit: int = 200,
    cwd: str | None = None,
) -> dict:
    """Scan merged PRs for unresolved review comment threads.

    Args:
        repo: Repository in owner/repo format
        limit: Max PRs to scan (default 200)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: prs (list), count (int)
    """
    from dev10x import github as gh
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await gh.unresolved_threads(repo=repo, limit=limit)).to_dict()


# ── CI monitoring tools ────────────────────────────────────────


@server.tool()
async def ci_check_status(
    pr_number: int,
    repo: str,
    required_only: bool = False,
    wait: bool = False,
    poll_interval: int = 30,
    initial_wait: int = 60,
    max_polls: int = 60,
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
        max_polls: Maximum number of polls (default 60)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with verdict, mergeable status, and check details
    """
    from dev10x import monitor as mon
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await mon.ci_check_status(
                pr_number=pr_number,
                repo=repo,
                required_only=required_only,
                wait=wait,
                poll_interval=poll_interval,
                initial_wait=initial_wait,
                max_polls=max_polls,
            )
        ).to_dict()


# ── Permission maintenance tools ───────────────────────────────


@server.tool()
async def update_paths(
    version: str | None = None,
    dry_run: bool = False,
    ensure_base: bool = False,
    generalize: bool = False,
    ensure_scripts: bool = False,
    ensure_reads: bool = False,
    init: bool = False,
    quiet: bool = False,
) -> dict:
    """Maintain Dev10x plugin permission settings across projects.

    Args:
        version: Target version to update to (auto-detects if omitted)
        dry_run: Preview changes without modifying files
        ensure_base: Add missing base permissions from projects.yaml
        generalize: Replace session-specific args with wildcards
        ensure_scripts: Verify all plugin scripts have allow rules
        ensure_reads: Emit per-skill Read rules with ~/ + /home/<user>/ twins
        init: Create userspace config from plugin default
        quiet: Suppress per-file details

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import permission as perm

    return (
        await perm.update_paths(
            version=version,
            dry_run=dry_run,
            ensure_base=ensure_base,
            generalize=generalize,
            ensure_scripts=ensure_scripts,
            ensure_reads=ensure_reads,
            init=init,
            quiet=quiet,
        )
    ).to_dict()


# ── Release tools ──────────────────────────────────────────────


@server.tool()
async def collect_prs(
    repo_path: str,
    from_tag: str | None = None,
    to_tag: str | None = None,
    ticket_pattern: str | None = None,
) -> dict:
    """Collect PRs between git tags for release notes.

    Args:
        repo_path: Path to the git repository
        from_tag: Start tag (optional)
        to_tag: End tag (optional)
        ticket_pattern: Regex override for ticket pattern

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import release as rel

    return (
        await rel.collect_prs(
            repo_path=repo_path,
            from_tag=from_tag,
            to_tag=to_tag,
            ticket_pattern=ticket_pattern,
        )
    ).to_dict()


# ── Skill index tools ─────────────────────────────────────────


@server.tool()
async def generate_skill_index(
    force: bool = False,
) -> dict:
    """Generate SKILLS.md and .skills-menu.txt files.

    Args:
        force: Regenerate even when cache is fresh

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import skill_index as idx

    return (await idx.generate_all(force=force)).to_dict()


# ── Skill audit tools ─────────────────────────────────────────


@server.tool()
async def audit_extract_session(
    jsonl_path: str,
    output_path: str | None = None,
) -> dict:
    """Extract a Claude Code JSONL session into readable markdown.

    Args:
        jsonl_path: Path to the JSONL session file
        output_path: Optional output file path

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import audit

    return (
        await audit.extract_session(
            jsonl_path=jsonl_path,
            output_path=output_path,
        )
    ).to_dict()


@server.tool()
async def audit_analyze_actions(
    transcript_path: str,
    output_path: str | None = None,
) -> dict:
    """Analyze actions from a session transcript.

    Args:
        transcript_path: Path to the markdown transcript
        output_path: Optional output file path

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import audit

    return (
        await audit.analyze_actions(
            transcript_path=transcript_path,
            output_path=output_path,
        )
    ).to_dict()


@server.tool()
async def audit_analyze_permissions(
    transcript_path: str,
    settings_path: str | None = None,
    output_path: str | None = None,
) -> dict:
    """Analyze permission friction from a session transcript.

    Args:
        transcript_path: Path to the markdown transcript
        settings_path: Optional settings.json path
        output_path: Optional output file path

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import audit

    return (
        await audit.analyze_permissions(
            transcript_path=transcript_path,
            settings_path=settings_path,
            output_path=output_path,
        )
    ).to_dict()


@server.tool()
async def audit_hook_log_path() -> dict:
    """Return the active audit-wrap JSONL log directory and today's log file.

    Resolves DEV10X_HOOK_AUDIT_DIR (default /tmp/Dev10x/hook-audit) so
    agents can locate hook-audit data without grep-hunting (GH-29).

    Returns:
        Dictionary with keys: audit_dir, today_log, today_log_exists,
        audit_dir_exists, available_logs, audit_disabled
    """
    from dev10x import audit

    return (await audit.hook_log_path()).to_dict()


@server.tool()
async def audit_hook_recent(
    limit: int = 50,
    hook_name: str | None = None,
    span_id: str | None = None,
    log_path: str | None = None,
) -> dict:
    """Return recent records from the audit-wrap JSONL log.

    Args:
        limit: Maximum records to return (most recent). 0 returns all.
        hook_name: Optional filter on the "hook" field.
        span_id: Optional filter on the "span_id" field.
        log_path: Optional explicit log file path. Defaults to today.

    Returns:
        Dictionary with keys: log_path, exists, count, records
    """
    from dev10x import audit

    return (
        await audit.hook_recent(
            limit=limit,
            hook_name=hook_name,
            span_id=span_id,
            log_path=log_path,
        )
    ).to_dict()


@server.tool()
async def record_upgrade(version: str | None = None) -> dict:
    """Record the currently-installed plugin version as applied.

    Called by Dev10x:upgrade-cleanup after a successful run so the
    SessionStart install-check stops emitting upgrade prompts.

    Args:
        version: Explicit version to record. Defaults to the value
            from $CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json.

    Returns:
        Dictionary with keys: version (str), path (str). Returns
        ``{"error": ...}`` when no version can be resolved.
    """
    from dev10x.domain.install_version import (
        read_plugin_version,
        write_applied_version,
    )

    resolved = version or read_plugin_version()
    if resolved is None:
        return {"error": "Could not resolve plugin version from plugin.json"}
    path = write_applied_version(plugin_version=resolved)
    return {"version": resolved, "path": str(path)}


def main() -> None:
    server.run()
