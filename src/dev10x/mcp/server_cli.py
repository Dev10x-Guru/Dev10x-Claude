"""MCP server registration for the Dev10x CLI server.

All @server.tool() registrations live here so servers/cli_server.py
becomes a thin 3-line uv shim. Tool handlers use lazy imports to
defer domain module loading until each tool is called.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP(name="Dev10x-cli")


# ── GitHub tools ────────────────────────────────────────────────


@server.tool()
async def detect_tracker(ticket_id: str) -> dict:
    """Detect issue tracker type from a ticket ID.

    Args:
        ticket_id: Ticket identifier (e.g., GH-15, TEAM-133, JIRA-42)

    Returns:
        Dictionary with keys: tracker, ticket_id, ticket_number, fixes_url
    """
    from dev10x.mcp import github as gh

    return (await gh.detect_tracker(ticket_id=ticket_id)).to_dict()


@server.tool()
async def pr_detect(arg: str) -> dict:
    """Detect PR context from a PR number, URL, or branch name.

    Args:
        arg: PR number (#123), full URL, or branch name

    Returns:
        Dictionary with keys: pr_number, repo, branch, state, head_ref
    """
    from dev10x.mcp import github as gh

    return (await gh.pr_detect(arg=arg)).to_dict()


@server.tool()
async def issue_get(number: int, repo: str | None = None) -> dict:
    """Get GitHub issue details.

    Args:
        number: Issue number
        repo: Repository (owner/repo). If omitted, uses current repo

    Returns:
        Dictionary with keys: title, state, body, labels, linked_prs
    """
    from dev10x.mcp import github as gh

    return (await gh.issue_get(number=number, repo=repo)).to_dict()


@server.tool()
async def issue_comments(number: int, repo: str | None = None) -> dict:
    """Get GitHub issue comments.

    Args:
        number: Issue number
        repo: Repository (owner/repo). If omitted, uses current repo

    Returns:
        Dictionary with key: comments (list of comment objects)
    """
    from dev10x.mcp import github as gh

    return (await gh.issue_comments(number=number, repo=repo)).to_dict()


@server.tool()
async def issue_create(
    title: str,
    body: str | None = None,
    labels: list[str] | None = None,
    milestone: str | None = None,
    repo: str | None = None,
) -> dict:
    """Create a GitHub issue.

    Args:
        title: Issue title
        body: Issue body text (optional)
        labels: List of label names to apply (optional)
        milestone: Milestone title to assign (optional)
        repo: Repository (owner/repo). If omitted, uses current repo

    Returns:
        Dictionary with keys: number, title, url
    """
    from dev10x.mcp import github as gh

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
    repo: str | None = None,
) -> dict:
    """Manage GitHub PR review comments and threads.

    Args:
        action: One of: list, get, reply, resolve
        pr_number: PR number (required for list, reply)
        comment_id: Comment ID (required for get, reply, resolve single)
        comment_ids: List of GraphQL node_ids for batch resolve
        body: Comment body text (required for reply)
        repo: Repository (owner/repo). If omitted, uses current repo

    Returns:
        Dictionary with action results (comments list or operation status)
    """
    from dev10x.mcp import github as gh

    return (
        await gh.pr_comments(
            action=action,
            pr_number=pr_number,
            comment_id=comment_id,
            comment_ids=comment_ids,
            body=body,
            repo=repo,
        )
    ).to_dict()


@server.tool()
async def pr_comment_reply(
    pr_number: int,
    comment_id: int,
    body: str,
    repo: str | None = None,
) -> dict:
    """Reply to a PR review comment thread.

    Args:
        pr_number: PR number
        comment_id: Root comment ID to reply to
        body: Reply text (supports markdown)
        repo: Repository (owner/repo). If omitted, uses current repo

    Returns:
        Dictionary with reply details (id, body, created_at)
    """
    from dev10x.mcp import github as gh

    return (
        await gh.pr_comment_reply(
            pr_number=pr_number,
            comment_id=comment_id,
            body=body,
            repo=repo,
        )
    ).to_dict()


@server.tool()
async def minimize_comments(
    node_ids: list[str],
    classifier: str = "OUTDATED",
    repo: str | None = None,
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

    Returns:
        Dictionary with batched mutation results keyed as m0, m1, ...
        each containing minimizedComment { isMinimized, minimizedReason }
    """
    from dev10x.mcp import github as gh

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
) -> dict:
    """Request review on a GitHub PR from users or teams.

    Args:
        pr_number: PR number
        reviewers: List of reviewer usernames or team names
        team: Whether reviewers are teams (vs users)
        repo: Repository (owner/repo). If omitted, uses current repo

    Returns:
        Dictionary with keys: requested_reviewers or requested_teams
    """
    from dev10x.mcp import github as gh

    return (
        await gh.request_review(
            pr_number=pr_number,
            reviewers=reviewers,
            team=team,
            repo=repo,
        )
    ).to_dict()


@server.tool()
async def detect_base_branch(base: str | None = None, force: bool = False) -> dict:
    """Detect the correct base branch for PRs in the current repository.

    Prefers develop/development, falls back to main/master/trunk.

    Args:
        base: Explicit base branch override
        force: Skip warning when overriding to non-development base

    Returns:
        Dictionary with keys: base_branch (str), has_develop (bool)
    """
    from dev10x.mcp import github as gh

    return (await gh.detect_base_branch(base=base, force=force)).to_dict()


@server.tool()
async def verify_pr_state(force: bool = False) -> dict:
    """Verify branch state before creating a PR.

    Args:
        force: Allow targeting a non-development base branch

    Returns:
        Dictionary with keys: branch_name, issue, base_branch
    """
    from dev10x.mcp import github as gh

    return (await gh.verify_pr_state(force=force)).to_dict()


@server.tool()
async def pre_pr_checks(base_branch: str | None = None) -> dict:
    """Run pre-PR quality checks (ruff, mypy, pytest).

    Args:
        base_branch: Base branch for diff comparison. Auto-detected if omitted.

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x.mcp import github as gh

    return (await gh.pre_pr_checks(base_branch=base_branch)).to_dict()


@server.tool()
async def create_pr(
    title: str,
    job_story: str,
    issue_id: str,
    fixes_url: str | None = None,
    base_branch: str | None = None,
) -> dict:
    """Create a draft PR with two-pass body generation.

    Args:
        title: PR title
        job_story: JTBD Job Story for the PR body
        issue_id: Ticket ID extracted from branch name
        fixes_url: Issue URL for the Fixes: line
        base_branch: Base branch. Auto-detected if omitted.

    Returns:
        Dictionary with keys: pr_number (int), url (str)
    """
    from dev10x.mcp import github as gh

    return (
        await gh.create_pr(
            title=title,
            job_story=job_story,
            issue_id=issue_id,
            fixes_url=fixes_url,
            base_branch=base_branch,
        )
    ).to_dict()


@server.tool()
async def generate_commit_list(pr_number: int, base_branch: str | None = None) -> dict:
    """Generate a linked commit list for a PR body.

    Args:
        pr_number: PR number for commit links
        base_branch: Base branch. Auto-detected if omitted.

    Returns:
        Dictionary with key: commit_list (str)
    """
    from dev10x.mcp import github as gh

    return (await gh.generate_commit_list(pr_number=pr_number, base_branch=base_branch)).to_dict()


@server.tool()
async def post_summary_comment(issue_id: str, summary_text: str) -> dict:
    """Post summary + checklist as first PR comment.

    Args:
        issue_id: Ticket ID for checklist substitution
        summary_text: Markdown bullet points (one per line)

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x.mcp import github as gh

    return (await gh.post_summary_comment(issue_id=issue_id, summary_text=summary_text)).to_dict()


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

    Returns:
        Dictionary with PR info (prepare) or operation results (send)
    """
    from dev10x.mcp import github as gh

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
async def push_safe(args: list[str], protected_branches: list[str] | None = None) -> dict:
    """Safely push git branches with protection for main/develop.

    Args:
        args: Arguments to pass to git push (e.g., ["origin", "branch-name"])
        protected_branches: List of branch names to protect (default: main, develop)

    Returns:
        Dictionary with keys: success (bool), branch, remote, blocked_reason (if blocked)
    """
    from dev10x.mcp import git as git_tools

    return (await git_tools.push_safe(args=args, protected_branches=protected_branches)).to_dict()


@server.tool()
async def rebase_groom(seq_path: str, base_ref: str) -> dict:
    """Rebase and groom commits using an interactive sequence file.

    Args:
        seq_path: Path to git rebase sequence file
        base_ref: Base ref to rebase onto (e.g., develop, main)

    Returns:
        Dictionary with keys: success (bool), commits_rewritten (int)
    """
    from dev10x.mcp import git as git_tools

    return (await git_tools.rebase_groom(seq_path=seq_path, base_ref=base_ref)).to_dict()


@server.tool()
async def create_worktree(
    branch: str,
    base: str | None = None,
    path: str | None = None,
) -> dict:
    """Create a new git worktree.

    Args:
        branch: Branch name for the worktree
        base: Base ref to create from (default: develop)
        path: Worktree path (default: ../.worktrees/{project}-NN)

    Returns:
        Dictionary with keys: worktree_path, branch, created (bool)
    """
    from dev10x.mcp import git as git_tools

    return (await git_tools.create_worktree(branch=branch, base=base, path=path)).to_dict()


@server.tool()
async def mass_rewrite(config_path: str) -> dict:
    """Rewrite multiple commit messages in one unattended rebase pass.

    Args:
        config_path: Path to JSON config file with rewrite instructions.

    Returns:
        Dictionary with keys: success (bool), output (str), error (str if failed)
    """
    from dev10x.mcp import git as git_tools

    return (await git_tools.mass_rewrite(config_path=config_path)).to_dict()


@server.tool()
async def start_split_rebase(commit_hash: str, base_branch: str = "develop") -> dict:
    """Start an interactive rebase to split a commit.

    Args:
        commit_hash: The commit hash to split
        base_branch: Base branch for the rebase (default: develop)

    Returns:
        Dictionary with keys: success (bool), output (str), error (str if failed)
    """
    from dev10x.mcp import git as git_tools

    return (
        await git_tools.start_split_rebase(commit_hash=commit_hash, base_branch=base_branch)
    ).to_dict()


@server.tool()
async def next_worktree_name(base_dir: str | None = None) -> dict:
    """Calculate the next available worktree path.

    Args:
        base_dir: Override worktrees parent directory (default: ../.worktrees)

    Returns:
        Dictionary with keys: path (str)
    """
    from dev10x.mcp import git as git_tools

    return (await git_tools.next_worktree_name(base_dir=base_dir)).to_dict()


@server.tool()
async def setup_aliases() -> dict:
    """Set up global git aliases for branch comparison operations.

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x.mcp import git as git_tools

    return (await git_tools.setup_aliases()).to_dict()


# ── Utility tools ───────────────────────────────────────────────


@server.tool()
async def mktmp(
    namespace: str,
    prefix: str,
    ext: str = "",
    directory: bool = False,
) -> dict:
    """Create a unique temp file or directory under /tmp/Dev10x/<namespace>/.

    Args:
        namespace: Subdirectory under /tmp/Dev10x/ (e.g., "git", "skill-audit")
        prefix: Filename prefix (e.g., "commit-msg", "pr-review")
        ext: File extension including dot (e.g., ".txt", ".json"). Ignored for directories.
        directory: If True, create a directory instead of a file.

    Returns:
        Dictionary with key: path (str) — the created temp file/directory path
    """
    from dev10x.mcp import utilities as util

    return await util.mktmp(namespace=namespace, prefix=prefix, ext=ext, directory=directory)


# ── Plan/Task tools ────────────────────────────────────────────


@server.tool()
async def plan_sync_set_context(
    args: list[str],
) -> dict:
    """Update plan context with key=value pairs.

    Args:
        args: K=V pairs (e.g., ["work_type=feature", "tickets=[...]"])

    Returns:
        Dictionary with keys: success (bool), updated_keys (list[str])
    """
    from dev10x.mcp import plan as plan_tools

    return await plan_tools.set_context(args=args)


@server.tool()
async def plan_sync_json_summary() -> dict:
    """Retrieve the current plan as a JSON summary.

    Returns:
        Dictionary with plan metadata, context, and task list.
        Empty dict if no plan exists.
    """
    from dev10x.mcp import plan as plan_tools

    return await plan_tools.json_summary()


@server.tool()
async def plan_sync_archive() -> dict:
    """Archive the current plan to a timestamped file and remove active plan.

    Returns:
        Dictionary with keys: success (bool), archive_name (str)
    """
    from dev10x.mcp import plan as plan_tools

    return await plan_tools.archive()


# ── GitHub review tools ────────────────────────────────────────


@server.tool()
async def resolve_review_thread(
    thread_ids: list[str] | None = None,
    comment_ids: list[str] | None = None,
    repo: str | None = None,
) -> dict:
    """Resolve GitHub PR review threads by thread ID or comment node ID.

    Accepts either direct thread IDs (PRRT_...) for immediate resolution,
    or comment node IDs that are looked up to find their parent thread first.

    Args:
        thread_ids: List of PRRT_ thread IDs to resolve directly
        comment_ids: List of GraphQL comment node IDs (thread lookup needed)
        repo: Repository (owner/repo). Required when using comment_ids.

    Returns:
        Dictionary with GraphQL mutation results per resolved thread
    """
    from dev10x.mcp import github as gh

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
) -> dict:
    """Check for unaddressed automated review comments on a PR.

    Args:
        pr_number: PR number to scan
        repo: Repository in owner/repo format

    Returns:
        Dictionary with keys: findings (list), count (int)
    """
    from dev10x.mcp import github as gh

    return (await gh.check_top_level_comments(pr_number=pr_number, repo=repo)).to_dict()


@server.tool()
async def unresolved_threads(
    repo: str,
    limit: int = 200,
) -> dict:
    """Scan merged PRs for unresolved review comment threads.

    Args:
        repo: Repository in owner/repo format
        limit: Max PRs to scan (default 200)

    Returns:
        Dictionary with keys: prs (list), count (int)
    """
    from dev10x.mcp import github as gh

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

    Returns:
        Dictionary with verdict, mergeable status, and check details
    """
    from dev10x.mcp import monitor as mon

    return await mon.ci_check_status(
        pr_number=pr_number,
        repo=repo,
        required_only=required_only,
        wait=wait,
        poll_interval=poll_interval,
        initial_wait=initial_wait,
        max_polls=max_polls,
    )


# ── Permission maintenance tools ───────────────────────────────


@server.tool()
async def update_paths(
    version: str | None = None,
    dry_run: bool = False,
    ensure_base: bool = False,
    generalize: bool = False,
    ensure_scripts: bool = False,
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
        init: Create userspace config from plugin default
        quiet: Suppress per-file details

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x.mcp import permission as perm

    return await perm.update_paths(
        version=version,
        dry_run=dry_run,
        ensure_base=ensure_base,
        generalize=generalize,
        ensure_scripts=ensure_scripts,
        init=init,
        quiet=quiet,
    )


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
    from dev10x.mcp import release as rel

    return await rel.collect_prs(
        repo_path=repo_path,
        from_tag=from_tag,
        to_tag=to_tag,
        ticket_pattern=ticket_pattern,
    )


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
    from dev10x.mcp import skill_index as idx

    return await idx.generate_all(force=force)


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
    from dev10x.mcp import audit

    return await audit.extract_session(
        jsonl_path=jsonl_path,
        output_path=output_path,
    )


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
    from dev10x.mcp import audit

    return await audit.analyze_actions(
        transcript_path=transcript_path,
        output_path=output_path,
    )


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
    from dev10x.mcp import audit

    return await audit.analyze_permissions(
        transcript_path=transcript_path,
        settings_path=settings_path,
        output_path=output_path,
    )


def main() -> None:
    server.run()
