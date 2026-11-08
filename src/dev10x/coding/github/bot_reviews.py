"""Whether each review bot has reviewed the current PR head (GH-1832).

Reading comment text is not enough to call a PR clean:

- review bots skip draft PRs, so an empty bot section on a draft means
  nothing ran, not that nothing was found;
- some bots submit a review with an empty body and put every finding in
  inline comments, so a body-only check reads them as silent;
- some bots never submit a review at all and post an issue comment
  instead, so there is no reviewed commit to compare with the head;
- a review of an earlier push says nothing about the current head.

One GraphQL query gathers the head, reviews, review threads and issue
comments, and :func:`summarize` folds them into one row per bot. The
fold is a pure function so recorded API payloads can test it directly.

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2).
"""

from __future__ import annotations

import fnmatch
import json
from typing import Any

from dev10x.coding.github import bot_review_config
from dev10x.core.github import _gateway
from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, Result, SuccessResult, ok

KIND_REVIEW = "review"
KIND_COMMENT = "comment"

# A review names the commit it saw; a bot that only comments does not,
# so its "at head" can only rest on time.
_BASIS = {KIND_REVIEW: "sha", KIND_COMMENT: "timestamp"}


def _query(*, owner: str, name: str, pr_number: int) -> str:
    return (
        "query { "
        f"repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) "
        f"{{ pullRequest(number: {pr_number}) {{ "
        "isDraft headRefOid "
        "commits(last: 1) { nodes { commit { oid committedDate } } } "
        "reviews(last: 100) { pageInfo { hasPreviousPage } nodes { "
        "author { __typename login } state body submittedAt commit { oid } } } "
        "reviewThreads(first: 100) { pageInfo { hasNextPage } nodes { isResolved "
        "first: comments(first: 1) { nodes { author { __typename login } createdAt } } "
        "last: comments(last: 1) { nodes { createdAt } } } } "
        "comments(last: 100) { pageInfo { hasPreviousPage } "
        "nodes { author { __typename login } createdAt } } "
        "} } }"
    )


# Which page flag says a 100-item window left items out. Reviews and
# comments read the newest 100, so older ones are missing; threads read
# the oldest 100, so newer ones are.
_WINDOWS = (
    ("reviews", "hasPreviousPage"),
    ("reviewThreads", "hasNextPage"),
    ("comments", "hasPreviousPage"),
)


def _truncated(*, pr: dict[str, Any]) -> list[str]:
    truncated: list[str] = []
    for connection, flag in _WINDOWS:
        container = pr.get(connection)
        page_info = container.get("pageInfo") if isinstance(container, dict) else None
        if isinstance(page_info, dict) and page_info.get(flag):
            truncated.append(connection)
    return truncated


def _is_bot(author: dict[str, Any]) -> bool:
    # The login regex in reviews.is_bot_login would let a human named
    # `claude-fan` satisfy a `claude*` blocking glob; GraphQL marks app
    # accounts by type, so trust that alone for a merge gate.
    return author.get("__typename") == "Bot"


def _matches_any(*, login: str, globs: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(login.lower(), glob.lower()) for glob in globs)


def _latest(*timestamps: str | None) -> str | None:
    return max((t for t in timestamps if t), default=None)


def _nodes(container: Any) -> list[dict[str, Any]]:
    if not isinstance(container, dict):
        return []
    return [n for n in container.get("nodes") or [] if isinstance(n, dict)]


def _first(container: Any) -> dict[str, Any]:
    nodes = _nodes(container)
    return nodes[0] if nodes else {}


def _new_row(*, login: str) -> dict[str, Any]:
    return {
        "login": login,
        "kind": KIND_COMMENT,
        "reviewed_sha": None,
        "review_state": None,
        "review_body_empty": None,
        "open_inline_comments": 0,
        "last_activity": None,
    }


def _collect_rows(*, pr: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def row_for(author: dict[str, Any] | None) -> dict[str, Any] | None:
        if not author or not _is_bot(author):
            return None
        login = bot_review_config.normalize_login(author.get("login"))
        if not login:
            return None
        return rows.setdefault(login.lower(), _new_row(login=login))

    submitted_reviews = [r for r in _nodes(pr.get("reviews")) if r.get("state") != "PENDING"]
    # Oldest first, so each bot's newest review is the one left standing.
    for review in sorted(submitted_reviews, key=lambda r: r.get("submittedAt") or ""):
        row = row_for(review.get("author"))
        if row is None:
            continue
        row["last_activity"] = _latest(row["last_activity"], review.get("submittedAt"))
        row["kind"] = KIND_REVIEW
        row["reviewed_sha"] = (review.get("commit") or {}).get("oid")
        row["review_state"] = review.get("state")
        row["review_body_empty"] = not (review.get("body") or "").strip()

    for thread in _nodes(pr.get("reviewThreads")):
        first = _first(thread.get("first"))
        row = row_for(first.get("author"))
        if row is None:
            continue
        row["last_activity"] = _latest(
            row["last_activity"],
            first.get("createdAt"),
            _first(thread.get("last")).get("createdAt"),
        )
        if not thread.get("isResolved"):
            row["open_inline_comments"] += 1

    for comment in _nodes(pr.get("comments")):
        row = row_for(comment.get("author"))
        if row is not None:
            row["last_activity"] = _latest(row["last_activity"], comment.get("createdAt"))

    return rows


def _at_head(
    *,
    row: dict[str, Any],
    head_sha: str | None,
    head_committed_at: str | None,
) -> bool | None:
    if row["kind"] == KIND_REVIEW:
        if not head_sha:
            return None
        return row["reviewed_sha"] == head_sha
    if not head_committed_at or not row["last_activity"]:
        return None
    return row["last_activity"] >= head_committed_at


def _row_reasons(*, row: dict[str, Any]) -> list[str]:
    login = row["login"]
    reasons: list[str] = []
    if row["at_head"] is False:
        reasons.append(f"{login}: last review is not at the PR head")
    elif row["at_head"] is None:
        reasons.append(f"{login}: cannot tell whether it reviewed the PR head")
    if row["at_head"] and row["review_state"] == "CHANGES_REQUESTED":
        reasons.append(f"{login}: requested changes at the PR head")
    if row["open_inline_comments"]:
        reasons.append(f"{login}: {row['open_inline_comments']} open inline comment(s)")
    return reasons


def summarize(
    *,
    pr: dict[str, Any],
    blocking_globs: tuple[str, ...],
) -> dict[str, Any]:
    """Fold one ``pullRequest`` GraphQL node into a per-bot status report."""
    head_sha = pr.get("headRefOid")
    head_committed_at = (_first(pr.get("commits")).get("commit") or {}).get("committedDate")
    is_draft = bool(pr.get("isDraft"))

    bots: list[dict[str, Any]] = []
    reasons: list[str] = []
    for row in sorted(_collect_rows(pr=pr).values(), key=lambda r: r["login"].lower()):
        row["at_head"] = _at_head(row=row, head_sha=head_sha, head_committed_at=head_committed_at)
        row["at_head_basis"] = _BASIS[row["kind"]]
        row["empty_body_with_inline"] = bool(
            row["review_body_empty"] and row["open_inline_comments"]
        )
        row["blocking"] = _matches_any(login=row["login"], globs=blocking_globs)
        if row["blocking"]:
            reasons.extend(_row_reasons(row=row))
        bots.append(row)

    missing = [
        glob
        for glob in blocking_globs
        if not any(_matches_any(login=b["login"], globs=(glob,)) for b in bots)
    ]
    draft_hint = " (PR is a draft — review bots skip drafts; mark it ready)" if is_draft else ""
    reasons.extend(f"{glob}: no activity on this PR{draft_hint}" for glob in missing)
    truncated = _truncated(pr=pr)
    reasons.extend(
        f"{connection}: more than 100 on this PR, so bot counts are incomplete"
        for connection in truncated
    )

    return {
        "head_sha": head_sha,
        "head_committed_at": head_committed_at,
        "is_draft": is_draft,
        "bots": bots,
        "blocking_bots": list(blocking_globs),
        "missing_blocking_bots": missing,
        "truncated": truncated,
        "ready": not reasons,
        "reasons": reasons,
    }


async def fetch_pull_request(*, ref: RepositoryRef, pr_number: int) -> Result[dict[str, Any]]:
    """The ``pullRequest`` node :func:`summarize` folds, read in one query."""
    return await _gateway._graphql_pull_request(
        _query(owner=ref.owner, name=ref.name, pr_number=pr_number),
        ref=ref,
        pr_number=pr_number,
    )


async def bot_review_status(
    *,
    pr_number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    ref = repo_result.value
    config = bot_review_config.resolve_blocking_bots(repo=str(ref))
    if not isinstance(config, SuccessResult):
        return config

    node = await fetch_pull_request(ref=ref, pr_number=pr_number)
    if not isinstance(node, SuccessResult):
        return node
    pr = node.value

    report = summarize(pr=pr, blocking_globs=config.value.globs)
    return ok(
        {
            "pr_number": pr_number,
            "repo": str(ref),
            **report,
            "config_source": config.value.source,
            "project_status": config.value.project_status,
        }
    )
