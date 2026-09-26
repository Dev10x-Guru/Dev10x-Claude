"""GitHub MCP tool implementations, one module per capability (ADR-0027).

Each function takes explicit parameters and returns Result types. All
public functions are async to avoid blocking the MCP event loop.

**Pattern: Gateway** (Fowler, *PoEAA*). This package is the Gateway to
the GitHub external system: every call to the ``gh`` CLI and the GitHub
REST/GraphQL APIs is funnelled through ``_gateway`` (``_gh_api_raw`` /
``async_run`` / ``async_run_script``), giving callers a uniform Python
surface and a single place to inject auth (``as_bot`` bot-token
routing) and the effective working directory. ADR-0006 records the
decision to keep this internal Gateway instead of the official GitHub
MCP server; ADR-0013 names the pattern across this package and
``subprocess_utils``.

**One seam per dependency (ADR-0027 D2).** Capability modules call a
dependency through its defining module — ``_gateway.async_run(...)``,
``pulls.pr_get(...)`` — never through a name bound by ``from ... import``.
A test therefore patches the defining module, and that one patch
intercepts every caller. ``tests/github/test_github_split.py`` fails a
test that patches a re-export on this facade while package code looks the
name up elsewhere.

This module only re-exports: production callers (``mcp/github_tools.py``,
``mcp/gate_query.py``, ``skills/notifications/_gh.py``) keep importing
from ``dev10x.github``.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, SuccessResult, err, ok
from dev10x.github import _gateway, labels, pulls
from dev10x.github._gateway import (
    _GH_RETRY_POLICY,
    _bot_env,
    _detect_repo,
    _gh_api,
    _gh_api_raw,
    _parse_gh_api_result,
    _resolve_repo,
    _run_and_parse,
)
from dev10x.github.bulk import (
    _bulk_execute,
    issues_bulk_create,
    issues_bulk_edit,
    milestones_bulk_create,
)
from dev10x.github.detection import (
    detect_base_branch,
    detect_tracker,
    pr_detect,
    pre_pr_checks,
    verify_pr_state,
)
from dev10x.github.issues import (
    _CLOSE_REASON_GH_VALUE,
    _issue_result,
    _resolve_comment_body,
    issue_close,
    issue_comment,
    issue_comment_delete,
    issue_comment_edit,
    issue_comments,
    issue_create,
    issue_edit,
    issue_get,
    issue_list,
    issue_reopen,
    triage_roster,
)
from dev10x.github.labels import (
    PR_LABEL_ACTIONS,
    _current_label_names,
    _label_names,
    _loads_or_empty,
    issue_labels,
    pr_labels,
)
from dev10x.github.milestones import (
    _resolve_milestone_number,
    milestone_close,
    milestone_create,
    milestone_edit,
    milestone_list,
    milestone_reopen,
)
from dev10x.github.notify import generate_commit_list, post_summary_comment, pr_notify
from dev10x.github.pulls import (
    _BASE_BRANCH_NAMES,
    _normalized_for_comparison,
    _set_pr_milestone,
    _unapplied_pr_fields,
    create_pr,
    pr_close,
    pr_get,
    pr_list,
    pr_ready,
    update_pr,
)
from dev10x.github.reviews import (
    _BOT_LOGIN_RE,
    _MINIMIZE_CLASSIFIERS,
    _PR_COMMENT_ACTIONS,
    _REACTION_GROUP_CONTENT_TO_KEY,
    _list_unresolved_threads,
    _normalize_reaction_groups,
    _pr_comment_edit,
    _pr_comment_get,
    _pr_comment_list,
    _pr_comment_reply,
    _pr_comment_resolve,
    check_top_level_comments,
    is_bot_login,
    minimize_comments,
    pr_comment_edit,
    pr_comment_reply,
    pr_comments,
    pr_issue_comment,
    pr_review_edit,
    request_review,
    resolve_review_thread,
    unresolved_threads,
)

__all__ = [
    # _gateway
    "_GH_RETRY_POLICY",
    "_bot_env",
    "_detect_repo",
    "_gh_api",
    "_gh_api_raw",
    "_parse_gh_api_result",
    "_resolve_repo",
    "_run_and_parse",
    # detection
    "detect_base_branch",
    "detect_tracker",
    "pr_detect",
    "pre_pr_checks",
    "verify_pr_state",
    # reviews
    "_BOT_LOGIN_RE",
    "_MINIMIZE_CLASSIFIERS",
    "_PR_COMMENT_ACTIONS",
    "_REACTION_GROUP_CONTENT_TO_KEY",
    "_list_unresolved_threads",
    "_normalize_reaction_groups",
    "_pr_comment_edit",
    "_pr_comment_get",
    "_pr_comment_list",
    "_pr_comment_reply",
    "_pr_comment_resolve",
    "check_top_level_comments",
    "is_bot_login",
    "minimize_comments",
    "pr_comment_edit",
    "pr_comment_reply",
    "pr_comments",
    "pr_issue_comment",
    "pr_review_edit",
    "request_review",
    "resolve_review_thread",
    "unresolved_threads",
    # labels
    "PR_LABEL_ACTIONS",
    "_current_label_names",
    "_label_names",
    "_loads_or_empty",
    "issue_labels",
    "pr_labels",
    # pulls
    "_BASE_BRANCH_NAMES",
    "_normalized_for_comparison",
    "_set_pr_milestone",
    "_unapplied_pr_fields",
    "create_pr",
    "pr_close",
    "pr_get",
    "pr_list",
    "pr_ready",
    "update_pr",
    # merge
    "_merge_as_bot",
    "_resolve_merge_bot",
    "merge_pr",
    # milestones
    "_resolve_milestone_number",
    "milestone_close",
    "milestone_create",
    "milestone_edit",
    "milestone_list",
    "milestone_reopen",
    # issues
    "_CLOSE_REASON_GH_VALUE",
    "_issue_result",
    "_resolve_comment_body",
    "issue_close",
    "issue_comment",
    "issue_comment_delete",
    "issue_comment_edit",
    "issue_comments",
    "issue_create",
    "issue_edit",
    "issue_get",
    "issue_list",
    "issue_reopen",
    "triage_roster",
    # bulk
    "_bulk_execute",
    "issues_bulk_create",
    "issues_bulk_edit",
    "milestones_bulk_create",
    # notify
    "generate_commit_list",
    "post_summary_comment",
    "pr_notify",
]


async def _resolve_merge_bot(
    *,
    use_bot: bool | None,
    admin: bool,
    auto: bool,
    repo_ref: str,
) -> tuple[str | None, dict[str, str] | None]:
    """Decide whether the bot merge transport runs, and mint its token once.

    Returns ``(fallback_reason, bot_env)``. A non-None reason is reported
    in the payload rather than raised: falling back to the engineer
    identity still merges (GH-1272), and a repo whose ruleset restricts
    who may merge depends on that.

    The token is returned rather than re-resolved at the call site so a
    second exchange cannot fail into engineer credentials while the
    payload still claims the merge was the bot's.
    """
    if use_bot is None:
        config = _gateway.AppConfig.load()
        wants_bot = config is not None and config.merge_bot
    else:
        wants_bot = use_bot
    if not wants_bot:
        return "not requested", None
    if admin or auto:
        # --admin and --auto have no REST merge equivalent; honouring
        # them matters more than the identity the merge carries.
        return "admin/auto merge has no bot transport", None
    bot_env = await _gateway._bot_env(repo=repo_ref)
    if bot_env is None:
        return "no installation token", None
    return None, bot_env


async def _merge_as_bot(
    *,
    pr_number: int,
    strategy: str,
    delete_branch: bool,
    repo_ref: str,
    expected_head_sha: str | None,
    bot_env: dict[str, str],
) -> Result[dict[str, Any]]:
    """Merge via ``PUT /pulls/{n}/merge`` under the installation token.

    An error here is not terminal — the caller degrades to the engineer
    identity, which is what a repo ruleset that excludes the bot needs.
    """
    fields: dict[str, str | int | list[str]] = {"merge_method": strategy}
    if expected_head_sha:
        fields["sha"] = expected_head_sha

    head_ref: str | None = None
    head_ref_error: str | None = None
    if delete_branch:
        pr = await pulls.pr_get(number=pr_number, repo=repo_ref)
        if isinstance(pr, SuccessResult):
            head_ref = pr.value.get("headRefName")
        else:
            head_ref_error = f"could not resolve head branch: {pr.error}"

    result = await _gateway._gh_api_raw(
        f"repos/{repo_ref}/pulls/{pr_number}/merge",
        method="PUT",
        fields=fields,
        repo=repo_ref,
        as_bot=True,
        bot_env=bot_env,
        timeout=60,
    )
    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    # A 200 whose body says otherwise is still a failed merge — the wire
    # contract's "a write is a request, not a receipt" rule.
    payload = labels._loads_or_empty(result.stdout)
    if isinstance(payload, dict) and payload.get("merged") is False:
        return err(str(payload.get("message") or "merge reported merged: false"))

    branch_deleted = False
    deletion_error = head_ref_error
    if head_ref:
        deletion = await _gateway._gh_api_raw(
            f"repos/{repo_ref}/git/refs/heads/{head_ref}",
            method="DELETE",
            repo=repo_ref,
            as_bot=True,
            bot_env=bot_env,
        )
        branch_deleted = deletion.returncode == 0
        if not branch_deleted:
            deletion_error = deletion.stderr.strip() or "ref deletion refused"

    return ok(
        {
            "pr_number": pr_number,
            "url": f"https://github.com/{repo_ref}/pull/{pr_number}",
            "strategy": strategy,
            "branch_deleted": branch_deleted,
            "branch_deletion_error": deletion_error,
            "admin": False,
            "auto": False,
            "repo": repo_ref,
            "expected_head_sha": expected_head_sha,
            "merged_as": "bot",
            "bot_fallback": None,
        }
    )


async def merge_pr(
    *,
    pr_number: int,
    strategy: str = "rebase",
    delete_branch: bool = True,
    admin: bool = False,
    auto: bool = False,
    repo: str | None = None,
    expected_head_sha: str | None = None,
    use_bot: bool | None = None,
) -> Result[dict[str, Any]]:
    """Merge a pull request via ``gh pr merge``.

    Symmetric to ``create_pr`` / ``update_pr`` — wraps the ``gh``
    CLI so callers reach the same code path through a structured
    MCP tool instead of a raw Bash command (GH-232). The subprocess
    is launched from the MCP server, so the PreToolUse hook that
    blocks raw ``gh pr merge`` Bash invocations does not apply.

    Args:
        pr_number: PR number to merge.
        strategy: One of ``rebase``, ``squash``, ``merge``.
        delete_branch: Pass ``--delete-branch`` when True.
        admin: Pass ``--admin`` when True — use administrator
            privileges to merge immediately, bypassing a
            required-review branch-protection rule the current
            account cannot satisfy (e.g. a solo maintainer who
            cannot self-approve). Gated upstream by the
            ``Dev10x:gh-pr-merge`` Step 5 admin-override prompt;
            the 7 non-approval checks still run first (GH-733).
        auto: Pass ``--auto`` when True — enable GitHub auto-merge
            so the PR merges once all branch-protection
            requirements are met (GH-733).
        repo: Repository (owner/repo). Auto-detected if omitted.
            Always passed as ``--repo`` to ``gh pr merge`` so the
            command never tries to check out the base branch
            locally — required for worktree safety (GH-773).
        expected_head_sha: Merge only if the PR head still points at
            this commit (GH-1267). The pre-merge gate verifies a
            specific head; without pinning it, a push landing between
            that verification and this call ships code no gate saw.
            Passed as ``--match-head-commit``, so a moved head fails
            the merge instead of silently widening it.
        use_bot: Execute the merge under the GitHub App identity so
            ``merged_by`` names the bot (GH-1272). ``None`` reads the
            durable ``github_app.merge_bot`` preference; ``True`` /
            ``False`` override it for one call. The bot path is
            skipped — with the reason reported in ``bot_fallback`` —
            when no installation token is available, or when ``admin``
            / ``auto`` is set, since neither has a REST equivalent.

    Returns:
        ok({"pr_number", "url", "strategy", "branch_deleted",
        "admin", "auto", "repo", "expected_head_sha", "merged_as",
        "bot_fallback"}) on success, err(...) otherwise.
    """
    if strategy not in {"rebase", "squash", "merge"}:
        return err(f"Invalid merge strategy: {strategy!r}. Use rebase, squash, or merge.")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    bot_fallback, bot_env = await _resolve_merge_bot(
        use_bot=use_bot, admin=admin, auto=auto, repo_ref=str(repo_ref)
    )
    if bot_fallback is None and bot_env is not None:
        bot_result = await _merge_as_bot(
            pr_number=pr_number,
            strategy=strategy,
            delete_branch=delete_branch,
            repo_ref=str(repo_ref),
            expected_head_sha=expected_head_sha,
            bot_env=bot_env,
        )
        if isinstance(bot_result, SuccessResult):
            return bot_result
        # A ruleset that excludes the bot refuses the REST merge; the
        # documented contract is to degrade, not to block the merge.
        bot_fallback = f"bot merge refused: {bot_result.error}"

    args = [
        "gh",
        "pr",
        "merge",
        str(pr_number),
        "--repo",
        str(repo_ref),
        f"--{strategy}",
    ]
    if delete_branch:
        args.append("--delete-branch")
    if admin:
        args.append("--admin")
    if auto:
        args.append("--auto")
    if expected_head_sha:
        args.extend(["--match-head-commit", expected_head_sha])

    result = await _gateway.async_run(args=args, timeout=60)

    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    return ok(
        {
            "pr_number": pr_number,
            "url": url,
            "strategy": strategy,
            "branch_deleted": delete_branch,
            "branch_deletion_error": None,
            "admin": admin,
            "auto": auto,
            "repo": str(repo_ref),
            "expected_head_sha": expected_head_sha,
            "merged_as": "engineer",
            "bot_fallback": bot_fallback,
        }
    )
