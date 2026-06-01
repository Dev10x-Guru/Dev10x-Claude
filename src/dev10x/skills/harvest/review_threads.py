"""Harvest PR review comments (threads) from GitHub.

Fetches inline review comments for a list of PR numbers via the GitHub
REST API (``gh api``).  Returns a flat list of :class:`ReviewComment`
objects that downstream consumers can cluster and score.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.subprocess_utils import async_run

logger = logging.getLogger(__name__)

#: REST fields fetched per review comment.  ``path`` + ``body`` are the
#: core content; the rest provide grouping and deduplication keys for
#: downstream clustering (#346).
_COMMENT_FIELDS = (
    "id,body,path,line,original_line,commit_id,created_at,"
    "pull_request_review_id,in_reply_to_id,user"
)

#: GitHub REST API page size cap.
_PAGE_SIZE = 100


@dataclass
class ReviewComment:
    """A single inline PR review comment."""

    pr_number: int
    repo: str
    comment_id: int
    body: str
    path: str
    line: int | None
    original_line: int | None
    author: str
    review_id: int | None
    in_reply_to_id: int | None
    created_at: str
    commit_id: str

    @classmethod
    def from_gh_json(
        cls,
        data: dict[str, Any],
        *,
        pr_number: int,
        repo: str,
    ) -> ReviewComment:
        user_obj = data.get("user") or {}
        author = user_obj.get("login", "") if isinstance(user_obj, dict) else ""
        return cls(
            pr_number=pr_number,
            repo=repo,
            comment_id=int(data.get("id", 0)),
            body=data.get("body", "") or "",
            path=data.get("path", "") or "",
            line=data.get("line"),
            original_line=data.get("original_line"),
            author=author,
            review_id=data.get("pull_request_review_id"),
            in_reply_to_id=data.get("in_reply_to_id"),
            created_at=data.get("created_at", ""),
            commit_id=data.get("commit_id", "") or "",
        )

    @property
    def is_reply(self) -> bool:
        """Return True when this comment is a reply in a thread."""
        return self.in_reply_to_id is not None


async def _fetch_pr_review_comments(
    *,
    repo: str,
    pr_number: int,
    page_size: int = _PAGE_SIZE,
) -> Result[list[ReviewComment]]:
    """Fetch all review comments for a single PR (handles pagination)."""
    all_comments: list[ReviewComment] = []
    page = 1

    while True:
        endpoint = f"repos/{repo}/pulls/{pr_number}/comments?per_page={page_size}&page={page}"
        args = ["gh", "api", endpoint]
        result = await async_run(args=args, timeout=30)

        if result.returncode != 0:
            return err(
                result.stderr.strip()
                or f"gh api failed for PR #{pr_number} (exit {result.returncode})"
            )

        raw = result.stdout.strip()
        if not raw:
            break

        try:
            items: list[dict[str, Any]] = json.loads(raw)
        except json.JSONDecodeError as exc:
            return err(f"Failed to parse review comments for PR #{pr_number}: {exc}")

        if not items:
            break

        for item in items:
            all_comments.append(
                ReviewComment.from_gh_json(
                    item,
                    pr_number=pr_number,
                    repo=repo,
                )
            )

        if len(items) < page_size:
            break
        page += 1

    logger.debug("Fetched %d review comments for %s#%d", len(all_comments), repo, pr_number)
    return ok(all_comments)


async def fetch_review_comments(
    *,
    repo: str,
    pr_numbers: list[int],
) -> Result[list[ReviewComment]]:
    """Fetch review comments for a list of PR numbers in *repo*.

    Calls :func:`_fetch_pr_review_comments` for each PR sequentially.
    Per-PR errors are logged at WARNING and that PR is skipped so the
    caller receives a partial but valid dataset (fail-soft semantics
    matching :func:`~closed_prs.fetch_closed_prs_multi`).

    Args:
        repo: Repository in ``owner/name`` format.
        pr_numbers: List of PR numbers to harvest.

    Returns:
        ``ok([ReviewComment, ...])`` — the combined list across all PRs.
        Never returns ``err``; per-PR failures appear in the log.
    """
    if not pr_numbers:
        return ok([])

    combined: list[ReviewComment] = []
    for pr_num in pr_numbers:
        result = await _fetch_pr_review_comments(repo=repo, pr_number=pr_num)
        if isinstance(result, ErrorResult):
            logger.warning(
                "Failed to fetch review comments for %s#%d: %s",
                repo,
                pr_num,
                result.error,
            )
        else:
            combined.extend(result.value)

    return ok(combined)


async def fetch_review_comments_multi(
    *,
    repo_prs: dict[str, list[int]],
) -> Result[dict[str, list[ReviewComment]]]:
    """Fetch review comments across multiple repositories.

    Args:
        repo_prs: Mapping of ``repo`` → ``[pr_number, ...]``.

    Returns:
        ``ok({"owner/name": [ReviewComment, ...]})`` on success.
        Returns ``err(...)`` when ``repo_prs`` is empty.
        Per-repo failures appear as empty lists with a WARNING log entry.
    """
    if not repo_prs:
        return err("repo_prs must be non-empty")

    mapping: dict[str, list[ReviewComment]] = {}
    for repo, pr_numbers in repo_prs.items():
        result = await fetch_review_comments(repo=repo, pr_numbers=pr_numbers)
        if isinstance(result, ErrorResult):
            logger.warning("Failed to harvest review comments from %s: %s", repo, result.error)
            mapping[repo] = []
        else:
            mapping[repo] = result.value

    return ok(mapping)
