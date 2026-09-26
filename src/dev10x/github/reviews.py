"""Review threads and comments capability (ADR-0027).

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2), so a
test patches ``dev10x.github._gateway.<name>`` and intercepts every caller.
"""

from __future__ import annotations

import json
import re
from typing import Any

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.github import _gateway


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
