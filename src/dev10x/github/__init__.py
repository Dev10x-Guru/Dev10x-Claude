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

import json
import logging
import os
import re
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.github.app_auth import AppConfig, get_bot_token
from dev10x.subprocess_utils import (
    async_run,
    async_run_script,
    parse_key_value_output,
)

log = logging.getLogger(__name__)


async def _detect_repo() -> str | None:
    result = await async_run(
        args=["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        timeout=10,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


async def _gh_api_raw(
    endpoint: str,
    *,
    method: str = "GET",
    fields: dict[str, str | int | list[str]] | None = None,
    jq: str | None = None,
    repo: str | None = None,
    as_bot: bool = False,
) -> subprocess.CompletedProcess[str]:
    args = ["gh", "api"]
    if method != "GET":
        args.extend(["-X", method])
    if jq:
        args.extend(["--jq", jq])
    if fields:
        for key, value in fields.items():
            if isinstance(value, list):
                for item in value:
                    args.extend(["-f", f"{key}[]={item}"])
            elif isinstance(value, int):
                args.extend(["-F", f"{key}={value}"])
            else:
                args.extend(["-f", f"{key}={value}"])
    args.append(endpoint)

    env = await _bot_env(repo=repo) if as_bot and repo else None
    return await async_run(args=args, timeout=30, env=env)


async def _gh_api(
    endpoint: str,
    *,
    method: str = "GET",
    fields: dict[str, str | int | list[str]] | None = None,
    jq: str | None = None,
    repo: str | None = None,
    as_bot: bool = False,
) -> Result[dict[str, Any]]:
    """Call ``gh api`` and enforce the Result[dict] contract centrally.

    Wraps :func:`_gh_api_raw` through :func:`_parse_gh_api_result` so
    JSON parsing and error handling live in one place rather than
    being repeated at every call site (ADR-0009, finding I8). Callers
    that need the raw ``CompletedProcess`` — custom GraphQL error
    handling or ``--jq`` scalar extraction — call :func:`_gh_api_raw`
    directly.
    """
    return _parse_gh_api_result(
        await _gh_api_raw(
            endpoint,
            method=method,
            fields=fields,
            jq=jq,
            repo=repo,
            as_bot=as_bot,
        )
    )


async def _bot_env(*, repo: str) -> dict[str, str] | None:
    try:
        ref = RepositoryRef.parse(repo)
    except ValueError:
        return None
    canonical_repo = str(ref)
    token = await get_bot_token(repo=canonical_repo)
    if token is None:
        if AppConfig.load() is not None:
            log.warning(
                "GitHub App auth configured but bot token exchange failed for %s — "
                "falling back to engineer credentials. Verify the App is installed "
                "on the repo and the private key matches the app_id.",
                canonical_repo,
            )
        return None
    return {**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token}


async def _resolve_repo(
    repo: str | None,
) -> Result[RepositoryRef]:
    resolved = repo or await _detect_repo()
    if not resolved:
        return err("Could not detect repository. Provide repo parameter.")
    try:
        return ok(RepositoryRef.parse(resolved))
    except ValueError as exc:
        return err(str(exc))


def _parse_gh_api_result(
    result: subprocess.CompletedProcess[str],
) -> Result[dict[str, Any]]:
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return ok({"raw_output": result.stdout})


async def _run_and_parse(
    script: str,
    *args: str,
    fallback: Callable[[str], dict[str, Any]] | None = None,
) -> Result[dict[str, Any]]:
    """Run a ``gh``-wrapper script and parse its stdout as JSON.

    Centralises the run → check-returncode → parse-JSON skeleton that was
    duplicated across the ``async_run_script`` wrappers (GH-837), where
    each copy had already drifted on its non-JSON fallback. On a non-zero
    exit the stderr becomes the error. On success stdout is parsed as
    JSON; if that fails, ``fallback`` (e.g. :func:`parse_key_value_output`)
    is applied to the raw stdout, otherwise the raw text is wrapped under
    ``raw_output``. Scripts that emit key=value rather than JSON pass
    ``fallback=parse_key_value_output`` — the JSON attempt is a harmless
    no-op for them and the fallback carries the parse.
    """
    result = await async_run_script(script, *args)
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        if fallback is not None:
            return ok(fallback(result.stdout))
        return ok({"raw_output": result.stdout})


async def detect_tracker(*, ticket_id: str) -> Result[dict[str, Any]]:
    return await _run_and_parse(
        "skills/gh-context/scripts/detect-tracker.sh",
        ticket_id,
        fallback=parse_key_value_output,
    )


async def pr_detect(*, arg: str) -> Result[dict[str, Any]]:
    return await _run_and_parse(
        "skills/gh-context/scripts/gh-pr-detect.sh",
        arg,
        fallback=parse_key_value_output,
    )


async def pr_get(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Get GitHub PR details as a structured payload (GH-267).

    Wraps ``gh pr view --json …`` so agents have a routed alternative
    to the hook-blocked ``gh pr view`` invocation.
    """
    args = [str(number)]
    if repo:
        args.append(repo)
    return await _run_and_parse(
        "skills/gh-context/scripts/gh-pr-get.sh",
        *args,
        fallback=parse_key_value_output,
    )


async def issue_get(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(number)]
    if repo:
        args.append(repo)
    return await _run_and_parse(
        "skills/gh-context/scripts/gh-issue-get.sh",
        *args,
        fallback=parse_key_value_output,
    )


async def issue_comments(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(number)]
    if repo:
        args.append(repo)
    return await _run_and_parse(
        "skills/gh-context/scripts/gh-issue-comments.sh",
        *args,
    )


async def issue_create(
    *,
    title: str,
    body: str | None = None,
    labels: list[str] | None = None,
    milestone: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [title]
    if body:
        args.extend(["--body", body])
    if labels:
        for label in labels:
            args.extend(["--label", label])
    if milestone:
        args.extend(["--milestone", milestone])
    if repo:
        args.extend(["--repo", repo])
    return await _run_and_parse(
        "skills/gh-context/scripts/gh-issue-create.sh",
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
    result = await _gh_api(f"repos/{resolved_repo}/pulls/comments/{comment_id}")
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
    result = await _gh_api(
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
    result = await _gh_api_raw("graphql", fields={"query": query})
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
    result = await _gh_api(
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
    result = await _gh_api(
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
    query_result = await _gh_api_raw(
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
    result = await _gh_api_raw(
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
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result

    fragments = " ".join(
        f"m{i}: minimizeComment(input: "
        f"{{subjectId: {json.dumps(nid)}, classifier: {classifier}}}) "
        f"{{ minimizedComment {{ isMinimized minimizedReason }} }}"
        for i, nid in enumerate(node_ids)
    )
    result = await _gh_api_raw(
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
        result = await _gh_api_raw(
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
        repo_result = await _resolve_repo(repo)
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
    repo_result = await _resolve_repo(repo)
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
    repo_result = await _resolve_repo(repo)
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

    result = await _gh_api(
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
    repo_result = await _resolve_repo(repo)
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
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    return await _gh_api(
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
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    result = await _gh_api(
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
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    fields: dict[str, str | int | list[str]] = {}
    if team:
        fields["team_reviewers"] = [r.split("/")[-1] for r in reviewers]
    else:
        fields["reviewers"] = reviewers

    result = await _gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/requested_reviewers",
        method="POST",
        fields=fields,
    )

    return result


async def detect_base_branch(
    *,
    base: str | None = None,
    force: bool = False,
) -> Result[dict[str, Any]]:
    args: list[str] = []
    if base:
        args.extend(["--base", base])
    if force:
        args.append("--force")

    result = await async_run_script(
        "skills/gh-pr-create/scripts/detect-base-branch.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    parsed = parse_key_value_output(result.stdout)
    return ok(
        {
            "base_branch": parsed.get("BASE_BRANCH", ""),
            "has_develop": bool(parsed.get("DEV_BRANCH", "")),
        }
    )


async def verify_pr_state(*, force: bool = False) -> Result[dict[str, Any]]:
    args: list[str] = []
    if force:
        args.append("--force")

    return await _run_and_parse(
        "skills/gh-pr-create/scripts/verify-state.sh",
        *args,
        fallback=parse_key_value_output,
    )


async def pre_pr_checks(*, base_branch: str | None = None) -> Result[dict[str, Any]]:
    args: list[str] = []
    if base_branch:
        args.append(base_branch)

    result = await async_run_script(
        "skills/gh-pr-create/scripts/pre-pr-checks.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip(), output=result.stdout.strip())

    return ok({"success": True, "output": result.stdout.strip()})


async def create_pr(
    *,
    title: str,
    job_story: str,
    issue_id: str,
    fixes_url: str | None = None,
    base_branch: str | None = None,
    closes: list[int] | None = None,
    draft: bool = True,
    head_repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [title, job_story, issue_id]
    args.append(fixes_url or "")
    args.append(base_branch or "")
    args.append(",".join(str(n) for n in closes) if closes else "")
    args.append("true" if draft else "false")
    args.append(head_repo or "")

    result = await async_run_script(
        "skills/gh-pr-create/scripts/create-pr.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    lines = result.stdout.strip().split("\n")
    pr_number = lines[-1]
    url = next((line for line in lines if line.startswith("http")), f"PR #{pr_number}")
    return ok({"pr_number": int(pr_number), "url": url})


async def update_pr(
    *,
    pr_number: int,
    body: str | None = None,
    title: str | None = None,
    base_branch: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    if body is None and title is None and base_branch is None:
        return err("update_pr requires at least one of: body, title, base_branch")

    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    fields: dict[str, str | int | list[str]] = {}
    if body is not None:
        fields["body"] = body
    if title is not None:
        fields["title"] = title
    if base_branch is not None:
        fields["base"] = base_branch

    result = await _gh_api_raw(
        f"repos/{repo_ref}/pulls/{pr_number}",
        method="PATCH",
        fields=fields,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    return ok({"pr_number": pr_number, "url": url})


async def merge_pr(
    *,
    pr_number: int,
    strategy: str = "rebase",
    delete_branch: bool = True,
    admin: bool = False,
    auto: bool = False,
    repo: str | None = None,
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

    Returns:
        ok({"pr_number", "url", "strategy", "branch_deleted",
        "admin", "auto", "repo"}) on success, err(...) otherwise.
    """
    if strategy not in {"rebase", "squash", "merge"}:
        return err(f"Invalid merge strategy: {strategy!r}. Use rebase, squash, or merge.")

    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

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

    result = await async_run(args=args, timeout=60)

    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    return ok(
        {
            "pr_number": pr_number,
            "url": url,
            "strategy": strategy,
            "branch_deleted": delete_branch,
            "admin": admin,
            "auto": auto,
            "repo": str(repo_ref),
        }
    )


async def pr_ready(
    *,
    pr_number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Mark a draft PR as ready for review via ``gh pr ready`` (GH-779).

    The ``draft`` flag is not PATCHable through the pulls endpoint, so
    :func:`update_pr` cannot un-draft a PR — un-drafting needs the
    dedicated GraphQL mutation that ``gh pr ready`` wraps. Symmetric to
    :func:`merge_pr`: the subprocess launches from the MCP server, so
    the PreToolUse hook that blocks raw ``gh pr ready`` Bash calls does
    not apply. Repos whose CI skips draft PRs must mark ready BEFORE
    monitoring CI, or the monitor polls a PR that never registers checks.

    Args:
        pr_number: PR number to mark ready.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        ok({"pr_number", "url", "repo"}) on success, err(...) otherwise.
    """
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    result = await async_run(
        args=["gh", "pr", "ready", str(pr_number), "--repo", str(repo_ref)],
        timeout=30,
    )

    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    return ok({"pr_number": pr_number, "url": url, "repo": str(repo_ref)})


async def milestone_close(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    result = await _gh_api_raw(
        f"repos/{repo_ref}/milestones/{number}",
        method="PATCH",
        fields={"state": "closed"},
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    url = f"https://github.com/{repo_ref}/milestone/{number}"
    return ok({"number": number, "state": "closed", "url": url})


async def milestone_create(
    *,
    title: str,
    description: str | None = None,
    due_on: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Create a GitHub milestone (GH-220).

    Wraps ``gh api repos/{r}/milestones --method POST``.

    Args:
        title: Milestone title (required, must be unique within repo).
        description: Optional milestone description.
        due_on: Optional ISO-8601 timestamp for the due date.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "title": str, "url": str}``.
    """
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    fields: dict[str, str | int | list[str]] = {"title": title}
    if description is not None:
        fields["description"] = description
    if due_on is not None:
        fields["due_on"] = due_on

    result = await _gh_api_raw(
        f"repos/{repo_ref}/milestones",
        method="POST",
        fields=fields,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")
    number = int(data.get("number", 0))
    return ok(
        {
            "number": number,
            "title": data.get("title", title),
            "url": f"https://github.com/{repo_ref}/milestone/{number}",
        }
    )


async def _issue_result(
    *,
    number: int,
    raw_url: str,
    repo: str | None,
    state: str | None = None,
) -> dict[str, Any]:
    """Assemble the ``{number, [state], url}`` payload for issue mutations.

    Resolves the canonical issue URL from ``repo``; when the repo cannot
    be resolved the ``gh`` command's own stdout (``raw_url``) is used as
    the URL. Shared by issue_edit/close/reopen, whose repo-resolution +
    URL-building tail was copy-pasted 3× (GH-838). ``state`` is omitted
    from the payload when ``None`` so ``issue_edit`` keeps its
    stateless ``{number, url}`` shape.
    """
    payload: dict[str, Any] = {"number": number}
    if state is not None:
        payload["state"] = state
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        payload["url"] = raw_url
    else:
        payload["url"] = f"https://github.com/{repo_result.value}/issues/{number}"
    return payload


async def issue_edit(
    *,
    number: int,
    title: str | None = None,
    body: str | None = None,
    milestone: str | None = None,
    labels: list[str] | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit a GitHub issue's metadata (GH-220).

    Wraps ``gh issue edit``. Accepts partial updates (any subset of
    title, body, milestone, labels).

    Args:
        number: Issue number to edit.
        title: New title (optional).
        body: New body text (optional). Written to a temp file to avoid
            heredoc/quoting issues at the subprocess boundary.
        milestone: Milestone title to assign (optional). Pass empty
            string to clear.
        labels: Replacement label list (optional). Each entry passed
            via ``--add-label``.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "url": str}``.
    """
    if title is None and body is None and milestone is None and not labels:
        return err("issue_edit requires at least one of: title, body, milestone, labels")

    args = ["gh", "issue", "edit", str(number)]
    if title is not None:
        args.extend(["--title", title])
    body_path: Path | None = None
    if body is not None:
        import tempfile

        fd_path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        fd_path.write(body)
        fd_path.close()
        body_path = Path(fd_path.name)
        args.extend(["--body-file", str(body_path)])
    if milestone is not None:
        args.extend(["--milestone", milestone])
    if labels:
        for label in labels:
            args.extend(["--add-label", label])
    if repo:
        args.extend(["--repo", repo])

    try:
        result = await async_run(args=args, timeout=30)
    finally:
        if body_path is not None:
            body_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok(await _issue_result(number=number, raw_url=result.stdout.strip(), repo=repo))


# gh's --reason wants the space spelling "not planned"; the wrapper takes the
# underscore spelling and translates at the gh boundary (GH-674).
_CLOSE_REASON_GH_VALUE: dict[str, str] = {
    "completed": "completed",
    "not_planned": "not planned",
}


async def issue_close(
    *,
    number: int,
    reason: str = "completed",
    comment: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Close a GitHub issue (GH-268, GH-674).

    Wraps ``gh issue close N --reason <reason> [--comment <body>]``.

    Args:
        number: Issue number to close.
        reason: ``"completed"`` (default) or ``"not_planned"``.
        comment: Optional final closing comment (Markdown supported).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "state": "closed", "url": str}``.
    """
    if reason not in _CLOSE_REASON_GH_VALUE:
        valid = ", ".join(repr(key) for key in _CLOSE_REASON_GH_VALUE)
        return err(f"reason must be one of {valid}, got: {reason!r}")

    args = ["gh", "issue", "close", str(number), "--reason", _CLOSE_REASON_GH_VALUE[reason]]
    if repo:
        args.extend(["--repo", repo])
    if comment is not None:
        args.extend(["--comment", comment])

    result = await async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok(
        await _issue_result(
            number=number, raw_url=result.stdout.strip(), repo=repo, state="closed"
        )
    )


async def issue_reopen(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Reopen a closed GitHub issue (GH-268).

    Wraps ``gh issue reopen N``.

    Args:
        number: Issue number to reopen.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "state": "open", "url": str}``.
    """
    args = ["gh", "issue", "reopen", str(number)]
    if repo:
        args.extend(["--repo", repo])

    result = await async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok(
        await _issue_result(number=number, raw_url=result.stdout.strip(), repo=repo, state="open")
    )


def _resolve_comment_body(*, body: str | None, body_file: str | None) -> Result[str]:
    """Resolve a comment body from inline text or a file path (GH-484).

    ``body`` is literal text — there is no ``@file`` / ``--body-file``
    expansion at this boundary, so passing ``body="@/path.md"`` posts the
    literal path string. To post the *contents* of a file, pass
    ``body_file`` instead.

    Args:
        body: Inline literal comment text, or ``None``.
        body_file: Path to a file whose contents become the body, or
            ``None``. Mutually exclusive with ``body``.

    Returns:
        ``ok(text)`` with the resolved body, or ``err(...)`` when both or
        neither source is supplied, or the file does not exist.
    """
    if body_file is not None:
        if body is not None:
            return err("Pass either 'body' or 'body_file', not both.")
        path = Path(body_file).expanduser()
        if not path.is_file():
            return err(f"body_file not found: {body_file}")
        return ok(path.read_text(encoding="utf-8"))
    if body is None:
        return err("Provide either 'body' (inline text) or 'body_file' (path).")
    return ok(body)


async def issue_comment(
    *,
    number: int,
    body: str | None = None,
    repo: str | None = None,
    body_file: str | None = None,
) -> Result[dict[str, Any]]:
    """Post a comment on a GitHub issue (GH-220).

    Wraps ``gh issue comment N --body-file <tmp>``. Body is written
    to a temp file to avoid heredoc/quoting issues.

    ``body`` is literal text — there is no ``@file`` expansion. To post
    the contents of a file, pass ``body_file`` instead (GH-484).

    Args:
        number: Issue number to comment on.
        body: Comment body (Markdown supported). Literal text.
        repo: Repository (owner/repo). Auto-detected if omitted.
        body_file: Path to a file whose contents become the body.
            Mutually exclusive with ``body``.

    Returns:
        On success: ``{"url": str}`` — the comment permalink.
    """
    import tempfile

    body_result = _resolve_comment_body(body=body, body_file=body_file)
    if isinstance(body_result, ErrorResult):
        return body_result
    resolved_body = body_result.value

    fd = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    fd.write(resolved_body)
    fd.close()
    body_path = Path(fd.name)

    args = ["gh", "issue", "comment", str(number), "--body-file", str(body_path)]
    if repo:
        args.extend(["--repo", repo])

    try:
        result = await async_run(args=args, timeout=30)
    finally:
        body_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"url": result.stdout.strip()})


async def issue_comment_edit(
    *,
    comment_id: int,
    body: str | None = None,
    repo: str | None = None,
    body_file: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit an existing GitHub issue or PR comment body (GH-283).

    Symmetric to ``issue_comment`` (POST) but uses PATCH against
    ``/repos/{owner}/{repo}/issues/comments/{id}``. Works on issue
    comments *and* PR issue-level comments (same endpoint).

    Body is written to a temp file to avoid heredoc/quoting issues at
    the gh CLI boundary, matching the ``issue_comment`` pattern.

    ``body`` is literal text — there is no ``@file`` expansion. To
    replace with the contents of a file, pass ``body_file`` (GH-484).

    Args:
        comment_id: Numeric ID of the comment to edit (from the
            ``/comments/<id>`` URL fragment).
        body: New body text (full replacement, not a delta). Literal text.
        repo: Repository (owner/repo). Auto-detected if omitted.
        body_file: Path to a file whose contents become the new body.
            Mutually exclusive with ``body``.

    Returns:
        On success: ``{"id": int, "body": str, "html_url": str}``.
    """
    import tempfile

    body_result = _resolve_comment_body(body=body, body_file=body_file)
    if isinstance(body_result, ErrorResult):
        return body_result
    resolved_body = body_result.value

    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    canonical_repo = str(repo_result.value)

    fd = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    fd.write(resolved_body)
    fd.close()
    body_path = Path(fd.name)

    endpoint = f"/repos/{canonical_repo}/issues/comments/{comment_id}"
    args = [
        "gh",
        "api",
        "-X",
        "PATCH",
        "-F",
        f"body=@{body_path}",
        endpoint,
    ]

    try:
        result = await async_run(args=args, timeout=30)
    finally:
        body_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return err(result.stderr.strip())

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")

    return ok(
        {
            "id": payload.get("id", comment_id),
            "body": payload.get("body", ""),
            "html_url": payload.get("html_url", ""),
        }
    )


async def issue_comment_delete(
    *,
    comment_id: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Delete a GitHub issue or PR comment (GH-283).

    Uses DELETE against ``/repos/{owner}/{repo}/issues/comments/{id}``.
    Works on issue comments *and* PR issue-level comments.

    Args:
        comment_id: Numeric ID of the comment to delete.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"deleted": True, "comment_id": int}``.
    """
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    canonical_repo = str(repo_result.value)

    endpoint = f"/repos/{canonical_repo}/issues/comments/{comment_id}"
    result = await async_run(
        args=["gh", "api", "-X", "DELETE", endpoint],
        timeout=30,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"deleted": True, "comment_id": comment_id})


async def issue_list(
    *,
    repo: str | None = None,
    state: str = "open",
    milestone: str | None = None,
    labels: list[str] | None = None,
    limit: int = 30,
    search: str | None = None,
) -> Result[dict[str, Any]]:
    """List GitHub issues (GH-220).

    Wraps ``gh issue list ... --json
    number,title,labels,milestone,state,url``.

    Args:
        repo: Repository (owner/repo). Auto-detected if omitted.
        state: Filter by state: ``open`` (default), ``closed``, ``all``.
        milestone: Filter by milestone title or number.
        labels: Filter by labels (issues matching ALL labels).
        limit: Max results to return (default 30).
        search: Free-text search filter passed via ``--search``.

    Returns:
        ``{"issues": [{number, title, labels, milestone, state, url}, ...]}``.
    """
    args = [
        "gh",
        "issue",
        "list",
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        "number,title,labels,milestone,state,url",
    ]
    if repo:
        args.extend(["--repo", repo])
    if milestone:
        args.extend(["--milestone", milestone])
    if labels:
        for label in labels:
            args.extend(["--label", label])
    if search:
        args.extend(["--search", search])

    result = await async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        issues = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    return ok({"issues": issues})


async def _bulk_execute(
    *,
    entries: list[dict[str, Any]],
    empty_error: str,
    identity_key: str,
    result_key: str,
    validate: Callable[[dict[str, Any]], str | None],
    perform: Callable[[dict[str, Any]], Awaitable[Result[dict[str, Any]]]],
    on_success: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> Result[dict[str, Any]]:
    """Run a per-entry GitHub operation across a batch (GH-222, GH-583).

    Shared skeleton for the ``*_bulk_*`` wrappers: guard the empty
    batch, iterate without short-circuiting, and split outcomes into
    ``result_key`` (successes) and ``failed`` so the caller sees the
    full batch result.

    Args:
        entries: Batch of per-operation dicts.
        empty_error: Error returned when ``entries`` is empty.
        identity_key: Field naming an entry in its ``failed`` record
            (e.g. ``"title"`` or ``"number"``).
        result_key: Key holding the successes (e.g. ``"created"``).
        validate: Returns an error message for an invalid entry, or
            ``None`` when the entry is well-formed.
        perform: Runs the per-entry operation, returning a ``Result``.
        on_success: Optional post-processor for a success payload
            (e.g. to backfill a field the per-entry call omits).
    """
    if not entries:
        return err(empty_error)

    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for entry in entries:
        validation_error = validate(entry)
        if validation_error is not None:
            failed.append({identity_key: entry.get(identity_key), "error": validation_error})
            continue
        result = await perform(entry)
        if isinstance(result, ErrorResult):
            failed.append({identity_key: entry.get(identity_key), "error": result.error})
        else:
            value = on_success(entry, result.value) if on_success else result.value
            succeeded.append(value)
    return ok({result_key: succeeded, "failed": failed})


async def milestones_bulk_create(
    *,
    milestones: list[dict[str, Any]],
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Create multiple GitHub milestones in one call (GH-222).

    Iterates milestone_create per entry; collects per-milestone
    successes and failures. The call does not short-circuit on
    individual failures so the caller sees the full batch outcome.

    Args:
        milestones: List of dicts; each entry accepts ``title`` (required),
            ``description`` (optional), and ``due_on`` (optional).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"created": [{title, number, url}, ...],
        "failed": [{title, error}, ...]}``. The wrapper never
        errors as long as at least one entry was attempted; entry-
        level failures land in ``failed``.
    """
    return await _bulk_execute(
        entries=milestones,
        empty_error="milestones_bulk_create requires at least one milestone",
        identity_key="title",
        result_key="created",
        validate=lambda entry: None if entry.get("title") else "missing title",
        perform=lambda entry: milestone_create(
            title=entry["title"],
            description=entry.get("description"),
            due_on=entry.get("due_on"),
            repo=repo,
        ),
    )


async def issues_bulk_create(
    *,
    issues: list[dict[str, Any]],
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Create multiple GitHub issues in one call (GH-222).

    Iterates issue_create per entry; collects per-issue successes
    and failures. Use for batch project scaffolding (e.g.,
    Dev10x:project-scope creating N tickets).

    Args:
        issues: List of dicts; each entry accepts ``title`` (required),
            ``body`` (optional), ``labels`` (optional list of str),
            ``milestone`` (optional).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        ``{"created": [{number, url, title}, ...],
        "failed": [{title, error}, ...]}``.
    """

    def _backfill_title(entry: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
        payload = dict(value)
        payload.setdefault("title", entry["title"])
        return payload

    return await _bulk_execute(
        entries=issues,
        empty_error="issues_bulk_create requires at least one issue",
        identity_key="title",
        result_key="created",
        validate=lambda entry: None if entry.get("title") else "missing title",
        perform=lambda entry: issue_create(
            title=entry["title"],
            body=entry.get("body"),
            labels=entry.get("labels"),
            milestone=entry.get("milestone"),
            repo=repo,
        ),
        on_success=_backfill_title,
    )


async def issues_bulk_edit(
    *,
    edits: list[dict[str, Any]],
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit multiple GitHub issues in one call (GH-222).

    Iterates issue_edit per entry; collects per-issue successes
    and failures. Use for batch milestone reassignment, label
    additions, or title/body fixes across many issues.

    Args:
        edits: List of dicts; each entry requires ``number`` and at
            least one of ``title``, ``body``, ``milestone``, ``labels``.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        ``{"edited": [{number, url}, ...],
        "failed": [{number, error}, ...]}``.
    """
    return await _bulk_execute(
        entries=edits,
        empty_error="issues_bulk_edit requires at least one edit",
        identity_key="number",
        result_key="edited",
        validate=lambda entry: (
            None if isinstance(entry.get("number"), int) else "missing or non-integer number"
        ),
        perform=lambda entry: issue_edit(
            number=entry["number"],
            title=entry.get("title"),
            body=entry.get("body"),
            milestone=entry.get("milestone"),
            labels=entry.get("labels"),
            repo=repo,
        ),
    )


async def generate_commit_list(
    *,
    pr_number: int,
    base_branch: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(pr_number)]
    if base_branch:
        args.append(base_branch)

    result = await async_run_script(
        "skills/gh-pr-create/scripts/generate-commit-list.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"commit_list": result.stdout.strip()})


async def post_summary_comment(
    *,
    issue_id: str,
    summary_text: str,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    env_vars: dict[str, str] = {}
    resolved_repo = repo or await _detect_repo()
    if resolved_repo:
        bot_env = await _bot_env(repo=resolved_repo)
        if bot_env is not None:
            env_vars["GH_TOKEN"] = bot_env["GH_TOKEN"]
            env_vars["GITHUB_TOKEN"] = bot_env["GITHUB_TOKEN"]
    result = await async_run_script(
        "skills/gh-pr-create/scripts/post-summary-comment.sh",
        issue_id,
        summary_text,
        env_vars=env_vars or None,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})


async def pr_notify(
    *,
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
) -> Result[dict[str, Any]]:
    plugin_root = Path(__file__).parents[3]
    script_path = plugin_root / "skills" / "gh-pr-monitor" / "scripts" / "pr-notify.py"

    if not script_path.exists():
        return err(f"Script not found: {script_path}")

    args = [
        "uv",
        "run",
        "--script",
        str(script_path),
        action,
        "--pr",
        str(pr_number),
        "--repo",
        repo,
    ]

    if action == "send":
        if channel:
            args.extend(["--channel", channel])
        if message:
            args.extend(["--message", message])
        if message_file:
            args.extend(["--message-file", message_file])
        if reviewer:
            args.extend(["--reviewer", reviewer])
        if skip_slack:
            args.append("--skip-slack")
        if skip_reviewers:
            args.append("--skip-reviewers")
        if skip_checklist:
            args.append("--skip-checklist")

    proc = await async_run(args=args, timeout=60)

    if proc.returncode != 0:
        return err(proc.stderr.strip())

    try:
        return ok(json.loads(proc.stdout))
    except json.JSONDecodeError:
        return ok({"success": True, "output": proc.stdout.strip()})


async def check_top_level_comments(
    *,
    pr_number: int,
    repo: str,
) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/gh-pr-merge/scripts/check-top-level-comments.sh",
        *repo.split("/"),
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
    result = await async_run_script(
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
