"""GitHub MCP tool implementations.

Extracted from cli_server.py — cohesive GitHub API and CLI operations.
Each function takes explicit parameters and returns Result types.
All public functions are async to avoid blocking the MCP event loop.

**Pattern: Gateway** (Fowler, *PoEAA*). This module is the Gateway to
the GitHub external system: every call to the ``gh`` CLI and the GitHub
REST/GraphQL APIs is funnelled through ``_gh_api_raw`` / ``async_run`` /
``async_run_script``, giving callers a uniform Python surface and a
single place to inject auth (``as_bot`` bot-token routing) and the
effective working directory. Callers never shell out to ``gh`` directly
— they go through this Gateway, so authentication, repo resolution, and
error wrapping stay in one layer. ADR-0006 records the decision to keep
this internal Gateway instead of the official GitHub MCP server;
ADR-0013 names the pattern across this module and ``subprocess_utils``.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, Result, SuccessResult, err, ok
from dev10x.domain.pr_body import (
    fixes_references,
    has_fixes_trailer,
    job_story_error,
    normalize_pr_body,
)
from dev10x.github import _gateway
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
from dev10x.subprocess_utils import parse_key_value_output

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

# Branch names that are never a legitimate PR head — HEAD on one of these
# when opening a PR signals a wrong/unbound working directory (GH-873 F1).
_BASE_BRANCH_NAMES = frozenset({"develop", "development", "main", "master", "trunk"})


async def pr_get(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Get GitHub PR details as a structured payload (GH-267).

    Wraps ``gh pr view --json …`` so agents have a routed alternative
    to the hook-blocked ``gh pr view`` invocation. The payload includes
    ``reviews`` and ``headRefOid`` (GH-917) so approval-state prechecks
    resolve human-vs-bot and current-vs-stale approvals through this tool.
    """
    args = [str(number)]
    if repo:
        args.append(repo)
    return await _gateway._run_and_parse(
        "skills/gh-context/scripts/gh-pr-get.sh",
        *args,
        fallback=parse_key_value_output,
    )


async def _pr_comment_get(
    *,
    resolved_repo: str,
    comment_id: int | str | None = None,
    **_: Any,
) -> Result[dict[str, Any]]:
    if comment_id is None:
        return err("comment_id required for 'get' action")
    result = await _gateway._gh_api(f"repos/{resolved_repo}/pulls/comments/{comment_id}")
    return result


async def _pr_comment_list(
    *,
    resolved_repo: str,
    pr_number: int | None = None,
    review_id: int | None = None,
    unresolved_only: bool = False,
    **_: Any,
) -> Result[dict[str, Any]]:
    if pr_number is None:
        return err("pr_number required for 'list' action")
    if unresolved_only:
        return await _list_unresolved_threads(
            resolved_repo=resolved_repo,
            pr_number=pr_number,
        )
    result = await _gateway._gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/comments?per_page=100",
    )
    if isinstance(result, ErrorResult):
        return result
    comments = result.value
    if review_id is not None and isinstance(comments, list):
        comments = [c for c in comments if c.get("pull_request_review_id") == review_id]
    # The comments REST endpoint returns a JSON array; wrap it so the
    # SuccessResult value satisfies the Mapping contract (ADR-0009)
    # while preserving the legacy {"value": [...]} wire shape. The
    # raw_output dict fallback passes through unchanged.
    if isinstance(comments, list):
        return ok({"value": comments})
    return ok(comments)


# Known automated-reviewer login pattern. Kept in sync with the `is_bot`
# login branch in skills/gh-pr-merge/scripts/top-level-comments.jq so the
# Python thread classifier and the jq top-level-comment classifier agree
# on which accounts are bots (GH-858 F1, hook-patterns.md dual-impl parity).
_BOT_LOGIN_RE = re.compile(
    r"claude|github-actions|coderabbit|sourcery|openai|codex|copilot",
    re.IGNORECASE,
)


def is_bot_login(login: str | None) -> bool:
    """True when a GitHub account login matches a known review-bot pattern.

    Conservative on purpose — the caller uses this to decide whether a
    review thread is bot-authored (auto-advanceable under AFK) or
    human-authored (must keep the supervisor in the loop), so a login it
    cannot confidently classify as a bot resolves to human.
    """
    return bool(login) and bool(_BOT_LOGIN_RE.search(login or ""))


async def _list_unresolved_threads(
    *,
    resolved_repo: str,
    pr_number: int,
) -> Result[dict[str, Any]]:
    repo_ref = (
        resolved_repo
        if isinstance(resolved_repo, RepositoryRef)
        else RepositoryRef.parse(str(resolved_repo))
    )
    query = (
        "query { "
        f"repository(owner: {json.dumps(repo_ref.owner)}, "
        f"name: {json.dumps(repo_ref.name)}) "
        f"{{ pullRequest(number: {pr_number}) "
        "{ reviewThreads(first: 100) { nodes { "
        "id isResolved isOutdated "
        "comments(first: 1) { nodes { "
        "databaseId body path line "
        "author { login } "
        "pullRequestReview { databaseId } "
        "reactionGroups { content users { totalCount } } "
        "} } "
        "} } } } }"
    )
    result = await _gateway._gh_api_raw("graphql", fields={"query": query})
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")
    threads = (
        data.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    unresolved: list[dict[str, Any]] = []
    for thread in threads:
        if thread.get("isResolved"):
            continue
        comments = thread.get("comments", {}).get("nodes", [])
        first = comments[0] if comments else {}
        first_author_login = (first.get("author") or {}).get("login")
        normalized = {
            "thread_id": thread.get("id"),
            "is_outdated": thread.get("isOutdated"),
            "author_type": "bot" if is_bot_login(first_author_login) else "human",
            **first,
        }
        reaction_groups = normalized.pop("reactionGroups", None)
        if reaction_groups is not None:
            normalized["reactions"] = _normalize_reaction_groups(reaction_groups)
        unresolved.append(normalized)
    return ok({"unresolved_threads": unresolved, "count": len(unresolved)})


_REACTION_GROUP_CONTENT_TO_KEY: dict[str, str] = {
    "THUMBS_UP": "+1",
    "THUMBS_DOWN": "-1",
    "LAUGH": "laugh",
    "HOORAY": "hooray",
    "CONFUSED": "confused",
    "HEART": "heart",
    "ROCKET": "rocket",
    "EYES": "eyes",
}


def _normalize_reaction_groups(reaction_groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert GraphQL reactionGroups to the REST reactions dict shape.

    The REST API returns:
      {"reactions": {"+1": 2, "-1": 0, "laugh": 0, ..., "total_count": 3}}

    The GraphQL API returns:
      [{"content": "THUMBS_UP", "users": {"totalCount": 2}}, ...]

    This normalises the GraphQL shape so callers always see the REST shape.
    """
    result: dict[str, Any] = {key: 0 for key in _REACTION_GROUP_CONTENT_TO_KEY.values()}
    total = 0
    for group in reaction_groups:
        content = group.get("content", "")
        count = group.get("users", {}).get("totalCount", 0)
        key = _REACTION_GROUP_CONTENT_TO_KEY.get(content)
        if key is not None:
            result[key] = count
            total += count
    result["total_count"] = total
    return result


async def _pr_comment_reply(
    *,
    resolved_repo: str,
    pr_number: int | None = None,
    comment_id: int | str | None = None,
    body: str | None = None,
    **_: Any,
) -> Result[dict[str, Any]]:
    if pr_number is None or comment_id is None or body is None:
        return err("pr_number, comment_id, and body required for 'reply'")
    try:
        comment_id_int = int(comment_id)
    except (TypeError, ValueError):
        return err(
            f"comment_id must be an integer for 'reply' "
            f"(GitHub rejects strings as in_reply_to). Got: {comment_id!r}"
        )
    result = await _gateway._gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/comments",
        method="POST",
        fields={"body": body, "in_reply_to": comment_id_int},
        repo=str(resolved_repo),
        as_bot=True,
    )
    return result


async def _pr_comment_edit(
    *,
    resolved_repo: str,
    comment_id: int | str | None = None,
    body: str | None = None,
    **_: Any,
) -> Result[dict[str, Any]]:
    if comment_id is None or body is None:
        return err("comment_id and body required for 'edit' action")
    try:
        comment_id_int = int(comment_id)
    except (TypeError, ValueError):
        return err(
            f"comment_id must be an integer for 'edit' (REST comment id). Got: {comment_id!r}"
        )
    result = await _gateway._gh_api(
        f"repos/{resolved_repo}/pulls/comments/{comment_id_int}",
        method="PATCH",
        fields={"body": body},
        repo=str(resolved_repo),
        as_bot=True,
    )
    return result


async def _pr_comment_resolve(
    *,
    resolved_repo: str,
    comment_id: int | str | None = None,
    comment_ids: list[str] | None = None,
    **_: Any,
) -> Result[dict[str, Any]]:
    """Resolve one or more PR review threads by comment node ID.

    GitHub's GraphQL API does not expose
    ``PullRequestReviewComment.pullRequestReviewThread`` (GH-329).
    Instead we fetch ``databaseId`` and the parent PR's ``reviewThreads``,
    then match threads whose first comment's ``databaseId`` equals the
    one returned for the requested node ID.
    """
    ids_to_resolve: list[str] = []
    if comment_ids:
        ids_to_resolve = comment_ids
    elif comment_id is not None:
        ids_to_resolve = [str(comment_id)]
    else:
        return err("comment_id or comment_ids required for 'resolve' action")

    # One GraphQL query per comment: fetch databaseId and the PR's reviewThreads
    # so we can match thread by first-comment databaseId without a separate
    # PR-number parameter (GH-329).
    node_fragments = " ".join(
        f"n{i}: node(id: {json.dumps(cid)}) "
        "{ ... on PullRequestReviewComment { "
        "databaseId "
        "pullRequest { reviewThreads(first: 100) { nodes { "
        "id comments(first: 1) { nodes { databaseId } } } } } "
        "} }"
        for i, cid in enumerate(ids_to_resolve)
    )
    query_result = await _gateway._gh_api_raw(
        "graphql",
        fields={"query": f"{{ {node_fragments} }}"},
    )
    if query_result.returncode != 0:
        return err(query_result.stderr.strip())

    try:
        query_data = json.loads(query_result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {query_result.stdout[:200]}")
    thread_ids: list[str] = []
    errors: list[str] = []
    for i, cid in enumerate(ids_to_resolve):
        node = query_data.get("data", {}).get(f"n{i}")
        if node is None:
            errors.append(
                f"Could not find thread for comment {cid}. "
                "The resolve action requires a GraphQL node_id, not a REST "
                "integer ID. Use the node_id field from a comment response."
            )
            continue
        comment_db_id = node.get("databaseId")
        threads = node.get("pullRequest", {}).get("reviewThreads", {}).get("nodes", [])
        matched_thread_id: str | None = None
        for thread in threads:
            first_comments = thread.get("comments", {}).get("nodes", [])
            if first_comments and first_comments[0].get("databaseId") == comment_db_id:
                matched_thread_id = thread.get("id")
                break
        if matched_thread_id and matched_thread_id.startswith("PRRT_"):
            thread_ids.append(matched_thread_id)
        else:
            errors.append(
                f"Could not find thread for comment {cid}. "
                "The resolve action requires a GraphQL node_id, not a REST "
                "integer ID. Use the node_id field from a comment response."
            )

    if not thread_ids:
        return err("; ".join(errors))

    resolve_fragments = " ".join(
        f"r{i}: resolveReviewThread(input: {{threadId: {json.dumps(tid)}}}) "
        f"{{ thread {{ id isResolved }} }}"
        for i, tid in enumerate(thread_ids)
    )
    result = await _gateway._gh_api_raw(
        "graphql",
        fields={"query": f"mutation {{ {resolve_fragments} }}"},
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    try:
        response: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")
    if errors:
        response["warnings"] = errors
    return ok(response)


_PR_COMMENT_ACTIONS: dict[str, Any] = {
    "get": _pr_comment_get,
    "list": _pr_comment_list,
    "reply": _pr_comment_reply,
    "edit": _pr_comment_edit,
    "resolve": _pr_comment_resolve,
}


_MINIMIZE_CLASSIFIERS = frozenset(
    {"ABUSE", "DUPLICATE", "OFF_TOPIC", "OUTDATED", "RESOLVED", "SPAM"}
)


async def minimize_comments(
    *,
    node_ids: list[str],
    classifier: str = "OUTDATED",
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    if not node_ids:
        return err("node_ids required (non-empty list of GraphQL node IDs)")
    if classifier not in _MINIMIZE_CLASSIFIERS:
        valid = ", ".join(sorted(_MINIMIZE_CLASSIFIERS))
        return err(f"Invalid classifier: {classifier!r}. Must be one of: {valid}")
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result

    fragments = " ".join(
        f"m{i}: minimizeComment(input: "
        f"{{subjectId: {json.dumps(nid)}, classifier: {classifier}}}) "
        f"{{ minimizedComment {{ isMinimized minimizedReason }} }}"
        for i, nid in enumerate(node_ids)
    )
    result = await _gateway._gh_api_raw(
        "graphql",
        fields={"query": f"mutation {{ {fragments} }}"},
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")


async def resolve_review_thread(
    *,
    thread_ids: list[str] | None = None,
    comment_ids: list[str] | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    if thread_ids:
        invalid = [tid for tid in thread_ids if not tid.startswith("PRRT_")]
        if invalid:
            return err(
                f"Invalid thread IDs (must start with PRRT_): {invalid}. "
                "Use comment_ids for GraphQL node IDs that need thread lookup."
            )
        resolve_fragments = " ".join(
            f"r{i}: resolveReviewThread(input: {{threadId: {json.dumps(tid)}}}) "
            f"{{ thread {{ id isResolved }} }}"
            for i, tid in enumerate(thread_ids)
        )
        result = await _gateway._gh_api_raw(
            "graphql",
            fields={"query": f"mutation {{ {resolve_fragments} }}"},
        )
        if result.returncode != 0:
            return err(result.stderr.strip())
        try:
            return ok(json.loads(result.stdout))
        except json.JSONDecodeError:
            return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")

    if comment_ids:
        repo_result = await _gateway._resolve_repo(repo)
        if isinstance(repo_result, ErrorResult):
            return repo_result
        return await _pr_comment_resolve(
            resolved_repo=str(repo_result.value),
            comment_ids=comment_ids,
        )

    return err("Provide either thread_ids (PRRT_...) or comment_ids (GraphQL node IDs).")


async def pr_comments(
    *,
    action: str,
    pr_number: int | None = None,
    comment_id: int | str | None = None,
    comment_ids: list[str] | None = None,
    body: str | None = None,
    review_id: int | None = None,
    unresolved_only: bool = False,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result

    handler = _PR_COMMENT_ACTIONS.get(action)
    if handler is None:
        supported = ", ".join(_PR_COMMENT_ACTIONS)
        return err(f"Unknown action: {action}. Supported: {supported}")

    return await handler(
        resolved_repo=repo_result.value,
        pr_number=pr_number,
        comment_id=comment_id,
        comment_ids=comment_ids,
        body=body,
        review_id=review_id,
        unresolved_only=unresolved_only,
    )


async def pr_comment_reply(
    *,
    pr_number: int,
    comment_id: int,
    body: str,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    try:
        comment_id_int = int(comment_id)
    except (TypeError, ValueError):
        return err(
            f"comment_id must be an integer "
            f"(GitHub rejects strings as in_reply_to). Got: {comment_id!r}"
        )

    result = await _gateway._gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/comments",
        method="POST",
        fields={"body": body, "in_reply_to": comment_id_int},
        repo=str(resolved_repo),
        as_bot=True,
    )

    return result


async def pr_comment_edit(
    *,
    comment_id: int,
    body: str,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit a PR inline review-thread comment body (GH-304).

    Uses PATCH against ``/repos/{owner}/{repo}/pulls/comments/{id}``.
    Distinct from :func:`issue_comment_edit` which targets the
    ``/issues/comments/`` endpoint (top-level issue + PR comments).
    Use this for inline review-thread comments (the ones tied to a
    file path + line number on a PR review).

    Thin public wrapper around :func:`_pr_comment_edit`; promoted to
    a stable name so the MCP boundary can expose it without leaking
    the private underscore-prefixed symbol.

    Args:
        comment_id: Numeric ID of the review-thread comment to edit
            (from the ``/comments/<id>`` URL fragment).
        body: New body text (full replacement, not a delta).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"id": int, "body": str, "html_url": str}``.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    return await _pr_comment_edit(
        resolved_repo=str(resolved_repo),
        comment_id=comment_id,
        body=body,
    )


async def pr_review_edit(
    *,
    pr_number: int,
    review_id: int,
    body: str,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit a submitted PR review BODY (GH-778).

    Uses PUT against
    ``/repos/{owner}/{repo}/pulls/{pr}/reviews/{review_id}`` — the only
    surface that can rewrite a submitted review's summary text.
    Distinct from :func:`pr_comment_edit` (inline review-thread
    comments) and :func:`issue_comment_edit` (top-level issue/PR
    comments). Use this to clear a stale severity token from a bot
    review body that still trips the pre-merge gate (Check 1b via
    :func:`check_top_level_comments`).

    Runs as the bot identity so a review authored by the session's
    GitHub App can be edited; falls back to engineer credentials when
    no bot token is configured.

    Args:
        pr_number: PR number the review belongs to.
        review_id: Numeric review ID (from the review's API URL).
        body: New review body text (full replacement, not a delta).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"id": int, "body": str, ...}``.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    return await _gateway._gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/reviews/{review_id}",
        method="PUT",
        fields={"body": body},
        repo=str(resolved_repo),
        as_bot=True,
    )


async def pr_issue_comment(
    *,
    pr_number: int,
    body: str,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    result = await _gateway._gh_api(
        f"repos/{resolved_repo}/issues/{pr_number}/comments",
        method="POST",
        fields={"body": body},
        repo=str(resolved_repo),
        as_bot=True,
    )

    return result


async def request_review(
    *,
    pr_number: int,
    reviewers: list[str],
    team: bool | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    fields: dict[str, str | int | list[str]] = {}
    if team:
        fields["team_reviewers"] = [r.split("/")[-1] for r in reviewers]
    else:
        fields["reviewers"] = reviewers

    result = await _gateway._gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/requested_reviewers",
        method="POST",
        fields=fields,
    )

    return result


async def _set_pr_milestone(
    *,
    pr_number: int,
    milestone: str,
    repo_ref: str,
) -> Result[int]:
    """Assign a milestone to a PR (GH-1098).

    A PR is an issue as far as milestones are concerned: the
    ``pulls/{n}`` endpoint has no ``milestone`` field, so the write
    goes through ``issues/{n}``. ``gh pr edit --milestone`` is avoided
    for the same reason ``create_pr``'s second pass avoids it — the
    GraphQL Projects-classic deprecation warning exits non-zero even
    on success (GH-41).
    """
    number_result = await _resolve_milestone_number(milestone=milestone, repo_ref=repo_ref)
    if isinstance(number_result, ErrorResult):
        return err(number_result.error)
    number = number_result.value

    result = await _gateway._gh_api_raw(
        f"repos/{repo_ref}/issues/{pr_number}",
        method="PATCH",
        fields={"milestone": number},
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    return ok(number)


async def create_pr(
    *,
    title: str,
    issue_id: str,
    job_story: str = "",
    body: str | None = None,
    head: str | None = None,
    milestone: str | None = None,
    fixes_url: str | None = None,
    base_branch: str | None = None,
    closes: list[int] | None = None,
    draft: bool = True,
    head_repo: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    # Assert-or-refuse against a wrong/unbound CWD (GH-873 F1). A
    # worktree-isolated swarm child that omits `cwd=` resolves to the
    # long-lived MCP process's own CWD (the orchestrator's), which is
    # typically the base branch — create-pr.sh would then push that base
    # branch and open a PR from it (a stray-branch failure). HEAD on a base
    # branch is never a legitimate PR source, so refuse loudly and name the
    # cause instead of silently pushing the wrong branch. GitContext resolves
    # through the effective-CWD seam, so an explicit `cwd=` (bound by the MCP
    # wrapper's use_cwd) is honoured here.
    from dev10x.domain.git_context import GitContext

    # The Job Story markers are checked on whatever text actually
    # becomes the PR body (GH-1073): with `body=` the caller supplies
    # the whole body, so validating `job_story` would police a string
    # that never reaches GitHub.
    story_error = job_story_error(job_story=body if body is not None else job_story)
    if story_error:
        return err(f"create_pr: {story_error}")

    # A body override skips the template assembly, so the arguments that
    # only feed that template would be dropped in silence — the same
    # silent-drop this parameter exists to fix. Refuse the combination.
    if body is not None:
        ignored = [name for name, value in (("fixes_url", fixes_url), ("closes", closes)) if value]
        if ignored:
            return err(
                "create_pr: body= supplies the whole PR body, so "
                f"{' and '.join(ignored)} would be dropped. Put the "
                "Fixes: / Closes: lines in body= itself, or drop body= "
                "and pass job_story= instead."
            )

    # Assert-or-refuse against a wrong/unbound CWD (GH-873 F1) — see the
    # note above. An explicit `head=` names the branch outright, so the
    # check applies to that instead of the resolved CWD (GH-1073).
    current_branch = head or await asyncio.to_thread(lambda: GitContext().branch)
    if current_branch in _BASE_BRANCH_NAMES:
        if head:
            return err(
                f"Refusing to create a PR from base branch '{current_branch}' "
                "(GH-873 F1): head= names a base branch. Pass the feature "
                "branch you want the PR opened from."
            )
        return err(
            f"Refusing to create a PR from base branch '{current_branch}' "
            "(GH-873 F1): HEAD is on a base branch, which usually means the "
            "call resolved to the wrong working directory. Pass an explicit "
            "cwd= (the worktree path) so the PR is created from your feature "
            "branch, not the base."
        )

    args = [title, job_story, issue_id]
    args.append(
        ""
        if body is not None
        else fixes_references(issue_id=issue_id, fixes_url=fixes_url, closes=closes)
    )
    args.append(base_branch or "")
    args.append(",".join(str(n) for n in closes) if closes else "")
    args.append("true" if draft else "false")
    args.append(head_repo or "")
    args.append(normalize_pr_body(body=body) if body is not None else "")
    args.append(head or "")
    args.append(repo or "")

    result = await _gateway.async_run_script(
        "skills/gh-pr-create/scripts/create-pr.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    lines = result.stdout.strip().split("\n")
    pr_number = lines[-1]
    url = next((line for line in lines if line.startswith("http")), f"PR #{pr_number}")
    payload: dict[str, Any] = {"pr_number": int(pr_number), "url": url}

    # Carries the resolved repo forward to the read-back below, so the
    # two calls cannot disagree about which repository this PR is in.
    # Stays None on the no-milestone path rather than forcing an extra
    # resolution round-trip — pr_get auto-detects from the same bound
    # CWD that create-pr.sh just used.
    resolved_repo = repo

    if milestone is not None:
        repo_result = await _gateway._resolve_repo(repo)
        if isinstance(repo_result, ErrorResult):
            return err(repo_result.error)
        resolved_repo = str(repo_result.value)
        milestone_result = await _set_pr_milestone(
            pr_number=payload["pr_number"],
            milestone=milestone,
            repo_ref=resolved_repo,
        )
        if isinstance(milestone_result, ErrorResult):
            # The PR is already open at this point, so an error naming
            # only the milestone failure strands it — name the PR too so
            # the caller can retry, comment on, or close it.
            return err(
                f"PR #{payload['pr_number']} ({payload['url']}) was created, "
                f"but assigning milestone {milestone!r} failed: "
                f"{milestone_result.error}"
            )
        payload["milestone"] = milestone_result.value

    # Read the trailer back off GitHub (GH-1274). Deriving one is not
    # proof it arrived — a write is a request, not a receipt (GH-1099) —
    # so only a fresh read settles it.
    verified = await pr_get(number=payload["pr_number"], repo=resolved_repo)
    if isinstance(verified, ErrorResult):
        # The PR exists and may well be fine; an unreadable verification
        # is not evidence of a bad body, so flag it rather than fail it.
        payload["fixes_trailer_verified"] = False
        payload["warning"] = (
            f"PR #{payload['pr_number']} was created but its body could not be "
            f"read back to confirm the Fixes: trailer: {verified.error}"
        )
        return ok(payload)

    if not has_fixes_trailer(body=str(verified.value.get("body", ""))):
        # Named like the milestone failure above: the PR is already open,
        # so an error that does not identify it strands it.
        return err(
            f"PR #{payload['pr_number']} ({payload['url']}) was created, but its "
            "body carries no Fixes: trailer — the hygiene bot will reject it and "
            "no linked issue will close on merge. Add the trailer with update_pr."
        )

    payload["fixes_trailer_verified"] = True
    return ok(payload)


async def update_pr(
    *,
    pr_number: int,
    body: str | None = None,
    title: str | None = None,
    base_branch: str | None = None,
    milestone: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    if body is None and title is None and base_branch is None and milestone is None:
        return err("update_pr requires at least one of: body, title, base_branch, milestone")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    fields: dict[str, str | int | list[str]] = {}
    if body is not None:
        fields["body"] = normalize_pr_body(body=body)
    if title is not None:
        fields["title"] = title
    if base_branch is not None:
        fields["base"] = base_branch

    if fields:
        result = await _gateway._gh_api_raw(
            f"repos/{repo_ref}/pulls/{pr_number}",
            method="PATCH",
            fields=fields,
        )

        if result.returncode != 0:
            return err(result.stderr.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    payload: dict[str, Any] = {"pr_number": pr_number, "url": url}

    if milestone is not None:
        milestone_result = await _set_pr_milestone(
            pr_number=pr_number,
            milestone=milestone,
            repo_ref=str(repo_ref),
        )
        if isinstance(milestone_result, ErrorResult):
            return err(milestone_result.error)
        payload["milestone"] = milestone_result.value

    if not fields:
        return ok(payload)

    # GH-1424: the payload used to be built entirely from the arguments,
    # so a PATCH the transport dropped read back as a completed write
    # (GH-1099). `.claude/rules/mcp-tools.md` names `update_pr` as needing
    # this; only `create_pr` actually did it.
    verified = await pr_get(number=pr_number, repo=str(repo_ref))
    if isinstance(verified, ErrorResult):
        payload["write_verified"] = False
        payload["warning"] = (
            f"PR #{pr_number} was updated but could not be read back to "
            f"confirm the change: {verified.error}"
        )
        return ok(payload)

    unapplied = _unapplied_pr_fields(sent=fields, observed=verified.value)
    if unapplied:
        return err(
            f"PR #{pr_number} ({url}) reports {', '.join(sorted(unapplied))} "
            f"unchanged after the update — the write did not land. Retry "
            f"update_pr rather than assuming the PR carries the new content."
        )

    payload["write_verified"] = True
    return ok(payload)


def _normalized_for_comparison(text: str) -> str:
    """Compare PR text ignoring differences GitHub introduces itself.

    GitHub stores bodies with CRLF line endings and may drop trailing
    whitespace, so a byte-exact comparison against what was sent reports
    a dropped write on every successful call.
    """
    return text.replace("\r\n", "\n").strip()


def _unapplied_pr_fields(
    *,
    sent: dict[str, str | int | list[str]],
    observed: dict[str, Any],
) -> set[str]:
    """Which of the PATCHed fields the PR does not actually carry.

    ``base`` is deliberately not checked: it is reported as
    ``baseRefName`` and a retarget can be refused server-side for
    reasons a caller cannot act on by retrying.
    """
    checked = {"body": "body", "title": "title"}
    return {
        field
        for field, observed_key in checked.items()
        if field in sent
        and _normalized_for_comparison(str(sent[field]))
        != _normalized_for_comparison(str(observed.get(observed_key, "")))
    }


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
        pr = await pr_get(number=pr_number, repo=repo_ref)
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
    payload = _loads_or_empty(result.stdout)
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


async def pr_ready(
    *,
    pr_number: int,
    repo: str | None = None,
    undo: bool = False,
) -> Result[dict[str, Any]]:
    """Flip a PR between draft and ready-for-review via ``gh pr ready`` (GH-779).

    The ``draft`` flag is not PATCHable through the pulls endpoint, so
    :func:`update_pr` cannot un-draft a PR — un-drafting needs the
    dedicated GraphQL mutation that ``gh pr ready`` wraps. Symmetric to
    :func:`merge_pr`: the subprocess launches from the MCP server, so
    the PreToolUse hook that blocks raw ``gh pr ready`` Bash calls does
    not apply. Repos whose CI skips draft PRs must mark ready BEFORE
    monitoring CI, or the monitor polls a PR that never registers checks.

    ``undo=True`` converts a published PR back to draft (GH-931 finding 2).
    Raw ``gh pr ready --undo`` is hook-blocked like every other form, so
    without this parameter the un-publish direction had no available path
    at all — and un-publishing is the *safe* direction, the correct
    response to spotting a problem after marking ready.

    Args:
        pr_number: PR number to flip.
        repo: Repository (owner/repo). Auto-detected if omitted.
        undo: Convert back to draft instead of marking ready.

    Returns:
        ok({"pr_number", "url", "repo", "draft"}) on success, err(...) otherwise.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    args = ["gh", "pr", "ready", str(pr_number), "--repo", str(repo_ref)]
    if undo:
        args.append("--undo")

    result = await _gateway.async_run(args=args, timeout=30)

    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    payload: dict[str, Any] = {"pr_number": pr_number, "url": url, "repo": str(repo_ref)}

    # GH-1424: `draft` used to be the `undo` argument echoed back, so it
    # could never disagree with the request and carried no information
    # about what GitHub did — while looking exactly like confirmation.
    # A write is a request, not a receipt (GH-1099): only a fresh read
    # settles it. GH-958 makes this load-bearing, since a force-push
    # silently returns a published PR to draft.
    verified = await pr_get(number=pr_number, repo=str(repo_ref))
    if isinstance(verified, ErrorResult):
        # The flip may well have landed; an unreadable verification is not
        # evidence that it did not. Report the request, flagged as unread.
        payload["draft"] = undo
        payload["draft_verified"] = False
        payload["warning"] = (
            f"PR #{pr_number} draft state could not be read back to confirm "
            f"the flip: {verified.error}"
        )
        return ok(payload)

    observed = bool(verified.value.get("isDraft"))
    if observed != undo:
        wanted = "draft" if undo else "ready for review"
        return err(
            f"PR #{pr_number} ({url}) is still "
            f"{'a draft' if observed else 'published'} after asking to make it "
            f"{wanted} — the write did not land. Retry pr_ready; a merge "
            f"attempted now fails with 'Pull Request is still a draft'."
        )

    payload["draft"] = observed
    payload["draft_verified"] = True
    return ok(payload)


async def pr_close(
    *,
    pr_number: int,
    comment: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Close a pull request via ``gh pr close`` (GH-924).

    Mirrors :func:`issue_close`'s shape — including the optional
    closing ``comment`` — so retiring a stale/superseded PR is one
    routed MCP call instead of the two-step "comment, then raw
    ``gh pr close``" workaround this issue was filed to eliminate.
    ``issue_close`` cannot be reused for this: `gh issue close`
    rejects a pull-request number outright.

    Args:
        pr_number: PR number to close.
        comment: Optional closing comment (Markdown supported),
            posted before the close so the rationale survives even
            if the close itself fails.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"pr_number": int, "state": "closed", "url": str}``.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    if comment is not None:
        comment_result = await _gateway._gh_api_raw(
            f"repos/{repo_ref}/issues/{pr_number}/comments",
            method="POST",
            fields={"body": comment},
            repo=str(repo_ref),
            as_bot=True,
        )
        if comment_result.returncode != 0:
            return err(comment_result.stderr.strip() or comment_result.stdout.strip())

    result = await _gateway.async_run(
        args=["gh", "pr", "close", str(pr_number), "--repo", str(repo_ref)],
        timeout=30,
    )
    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    return ok({"pr_number": pr_number, "state": "closed", "url": url})


async def pr_list(
    *,
    repo: str | None = None,
    state: str = "open",
    limit: int = 30,
    search: str | None = None,
) -> Result[dict[str, Any]]:
    """List GitHub pull requests (GH-1359).

    Wraps ``gh pr list ... --json
    number,title,state,headRefName,isDraft,mergedAt,url``, mirroring
    :func:`issue_list`'s shape. `Dev10x:diag-friction` filed this after
    finding no ``pr_list`` MCP tool and no ``gh pr list`` rule in
    ``command-skill-map.yaml`` — listing PRs had nowhere to go but raw
    ``gh pr list``, uncatalogued and prompting on every call.

    Args:
        repo: Repository (owner/repo). Auto-detected if omitted.
        state: Filter by state: ``open`` (default), ``closed``, ``merged``,
            ``all``.
        limit: Max results to return (default 30).
        search: Free-text search filter passed via ``--search``.

    Returns:
        ``{"prs": [{number, title, state, headRefName, isDraft,
        mergedAt, url}, ...]}``.
    """
    if state not in ("open", "closed", "merged", "all"):
        return err(f"Invalid PR state {state!r}: must be 'open', 'closed', 'merged', or 'all'.")

    args = [
        "gh",
        "pr",
        "list",
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        "number,title,state,headRefName,isDraft,mergedAt,url",
    ]
    if repo:
        args.extend(["--repo", repo])
    if search:
        args.extend(["--search", search])

    result = await _gateway.async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        prs = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    return ok({"prs": prs})


async def check_top_level_comments(
    *,
    pr_number: int,
    repo: str,
) -> Result[dict[str, Any]]:
    try:
        ref = RepositoryRef.parse(repo)
    except ValueError as exc:
        return err(str(exc))
    result = await _gateway.async_run_script(
        "skills/gh-pr-merge/scripts/check-top-level-comments.sh",
        ref.owner,
        ref.name,
        str(pr_number),
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        findings = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    # GH-808 F1: bucket by severity so callers can distinguish hard-blocking
    # findings from non-blocking INFO/NOTE/SUGGESTION ones that still need an
    # explicit disposition before the gate reads clean. `findings`/`count`
    # stay for backward compatibility; the bucketed keys are additive.
    blocking = [f for f in findings if f.get("severity") == "blocking"]
    needs_disposition = [f for f in findings if f.get("severity") == "info"]
    return ok(
        {
            "findings": findings,
            "count": len(findings),
            "blocking": blocking,
            "blocking_count": len(blocking),
            "needs_disposition": needs_disposition,
            "needs_disposition_count": len(needs_disposition),
        }
    )


async def unresolved_threads(
    *,
    repo: str,
    pr_number: int | None = None,
    limit: int = 200,
) -> Result[dict[str, Any]]:
    # A single-PR check delegates to the per-PR GraphQL path (one
    # query, sub-2s). The repo-wide sweep below fans out to ~2 gh
    # subprocesses per merged PR and times out at scale (GH-710).
    if pr_number is not None:
        return await _list_unresolved_threads(
            resolved_repo=repo,
            pr_number=pr_number,
        )
    result = await _gateway.async_run_script(
        "skills/gh-pr-doctor/scripts/gh-unresolved-threads.py",
        "--repo",
        repo,
        "--limit",
        str(limit),
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    return ok({"prs": prs, "count": len(prs)})
