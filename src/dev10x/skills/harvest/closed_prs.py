"""Harvest closed/merged PRs from a GitHub repository.

Reuses the project-audit Phase-1 ``gh pr list`` pattern to fetch PR
metadata in bulk. Callers that want review threads should pass the
returned PR numbers to ``review_threads.fetch_review_comments``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.subprocess_utils import async_run

logger = logging.getLogger(__name__)

#: Fields fetched per PR — chosen to minimise payload while providing
#: everything downstream clustering needs.
_PR_FIELDS = "number,title,body,mergedAt,closedAt,state,labels,author,baseRefName"

#: Maximum PRs returned per ``gh pr list`` call (GitHub API cap is 1000,
#: but we cap at 200 to match the project-audit Phase-1 heuristic and
#: keep harvest latency reasonable for large repos).
DEFAULT_LIMIT = 200


@dataclass
class ClosedPR:
    """Lightweight representation of a closed or merged PR."""

    number: int
    title: str
    body: str
    state: str
    merged_at: str | None
    closed_at: str | None
    base_ref: str
    labels: list[str] = field(default_factory=list)
    author: str = ""

    @classmethod
    def from_gh_json(cls, data: dict[str, Any]) -> ClosedPR:
        labels = [
            lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
            for lbl in data.get("labels", [])
        ]
        author_obj = data.get("author") or {}
        author_login = author_obj.get("login", "") if isinstance(author_obj, dict) else ""
        return cls(
            number=int(data.get("number", 0)),
            title=data.get("title", ""),
            body=data.get("body", "") or "",
            state=data.get("state", ""),
            merged_at=data.get("mergedAt"),
            closed_at=data.get("closedAt"),
            base_ref=data.get("baseRefName", ""),
            labels=labels,
            author=author_login,
        )


async def fetch_closed_prs(
    *,
    repo: str,
    limit: int = DEFAULT_LIMIT,
    state: str = "merged",
) -> Result[list[ClosedPR]]:
    """Fetch closed or merged PRs for *repo*.

    Args:
        repo: Repository in ``owner/name`` format.
        limit: Maximum number of PRs to return.
        state: ``"merged"`` (default) or ``"closed"`` or ``"all"``.
            ``"all"`` returns both open and closed; callers that want
            only closed-but-not-merged PRs should use ``"closed"``
            and filter by ``merged_at is None``.

    Returns:
        ``ok([ClosedPR, ...])`` on success, ``err("...")`` on failure.
    """
    args = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        _PR_FIELDS,
    ]
    result = await async_run(args=args, timeout=60)
    if result.returncode != 0:
        return err(result.stderr.strip() or f"gh pr list failed (exit {result.returncode})")

    raw = result.stdout.strip()
    if not raw:
        return ok([])

    try:
        items: list[dict[str, Any]] = json.loads(raw)
    except json.JSONDecodeError as exc:
        return err(f"Failed to parse gh pr list output: {exc}")

    prs = [ClosedPR.from_gh_json(item) for item in items]
    logger.debug("Fetched %d PRs from %s (state=%s)", len(prs), repo, state)
    return ok(prs)


async def fetch_closed_prs_multi(
    *,
    repos: list[str],
    limit: int = DEFAULT_LIMIT,
    state: str = "merged",
) -> Result[dict[str, list[ClosedPR]]]:
    """Fetch closed PRs from multiple repositories.

    Calls :func:`fetch_closed_prs` for each repo sequentially and
    returns a mapping of repo → PR list.  On per-repo failure, the
    error is logged and that repo is mapped to an empty list so
    callers always receive a complete keyed dict.

    Args:
        repos: List of ``owner/name`` repository strings.
        limit: Maximum PRs per repo.
        state: State filter forwarded to :func:`fetch_closed_prs`.

    Returns:
        ``ok({"owner/name": [ClosedPR, ...]})`` on success.
        Returns ``err(...)`` when ``repos`` is empty.
        Per-repo failures appear as empty lists and are logged at WARNING.
    """
    if not repos:
        return err("repos must be non-empty")

    mapping: dict[str, list[ClosedPR]] = {}
    for repo in repos:
        result = await fetch_closed_prs(repo=repo, limit=limit, state=state)
        if isinstance(result, ErrorResult):
            logger.warning("Failed to harvest PRs from %s: %s", repo, result.error)
            mapping[repo] = []
        else:
            mapping[repo] = result.value

    return ok(mapping)
