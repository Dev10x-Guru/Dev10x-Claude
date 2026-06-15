"""Cluster & score PR review-comment patterns (GH-346).

Self-contained learning step for the review-bot initiative: fetches
merged-PR review comments, groups them into recurring candidate
patterns, and scores each by frequency so the top-N findings can feed
a candidate-rules report (GH-347).

This module is intentionally free-standing — it fetches its own data
via ``gh`` rather than depending on the GH-345 harvest module, which
was removed in GH-540 as unreachable code. It is wired as the
``cluster_review_comments`` MCP tool in ``github_tools.py`` so it stays
production-reachable.

Internal functions return ``Result[T]`` per ADR-0009; the
``@server.tool()`` boundary calls ``.to_dict()``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.subprocess_utils import async_run

logger = logging.getLogger(__name__)

# Words that carry no signal for clustering review feedback. Kept small
# and review-specific rather than a full NLP stop-list.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "but",
        "if",
        "it",
        "we",
        "you",
        "i",
        "should",
        "would",
        "could",
        "can",
        "will",
        "please",
        "here",
        "there",
        "not",
        "no",
        "yes",
        "do",
        "does",
        "with",
        "as",
        "at",
        "by",
        "from",
    }
)

# Number of significant tokens kept in a cluster signature. A short
# signature groups paraphrased feedback ("rename pm to payment_method"
# and "payment_method, not pm") under one pattern without over-merging.
_SIGNATURE_TOKENS = 6

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S+")
_NON_WORD = re.compile(r"[^a-z0-9\s]")
_DIGITS = re.compile(r"\b\d+\b")


@dataclass(frozen=True)
class ReviewComment:
    """A single inline review comment harvested from a merged PR."""

    repo: str
    pr_number: int
    body: str
    path: str = ""
    line: int | None = None
    author: str = ""


@dataclass(frozen=True)
class CandidatePattern:
    """A recurring review-comment pattern, scored by frequency."""

    signature: str
    frequency: int
    files: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return self.frequency

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "frequency": self.frequency,
            "score": self.score,
            "files": self.files,
            "authors": self.authors,
            "examples": self.examples,
        }


def _normalize(body: str) -> str:
    """Reduce a comment body to a stable clustering signature.

    Strips code spans, URLs, numbers, and punctuation, drops stopwords,
    then keeps the first ``_SIGNATURE_TOKENS`` significant tokens. Two
    comments that share a signature land in the same cluster.
    """
    text = _FENCED_CODE.sub(" ", body)
    text = _INLINE_CODE.sub(" ", text)
    text = _URL.sub(" ", text)
    text = text.lower()
    text = _DIGITS.sub(" ", text)
    text = _NON_WORD.sub(" ", text)
    tokens = [t for t in text.split() if t and t not in _STOPWORDS]
    return " ".join(tokens[:_SIGNATURE_TOKENS])


def cluster_and_score(
    comments: list[ReviewComment],
    *,
    top_n: int = 20,
) -> list[CandidatePattern]:
    """Group comments by normalized signature and rank by frequency.

    Comments whose signature is empty (pure code/URL/punctuation) are
    skipped. Ordering is deterministic: frequency desc, then number of
    distinct files desc, then signature asc.
    """
    buckets: dict[str, list[ReviewComment]] = {}
    for comment in comments:
        signature = _normalize(comment.body)
        if not signature:
            continue
        buckets.setdefault(signature, []).append(comment)

    patterns = [
        CandidatePattern(
            signature=signature,
            frequency=len(members),
            files=sorted({m.path for m in members if m.path}),
            authors=sorted({m.author for m in members if m.author}),
            examples=[m.body for m in members[:3]],
        )
        for signature, members in buckets.items()
    ]
    patterns.sort(key=lambda p: (-p.frequency, -len(p.files), p.signature))
    return patterns[:top_n]


async def _detect_repo() -> str | None:
    result = await async_run(
        args=["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


async def _merged_pr_numbers(*, repo: str, limit: int) -> Result[list[int]]:
    result = await async_run(
        args=[
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--limit",
            str(limit),
            "--json",
            "number",
        ],
        timeout=60,
    )
    if result.returncode != 0:
        return err(result.stderr.strip() or "gh pr list failed")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return err("could not parse gh pr list output")
    return ok([int(item["number"]) for item in payload])


async def _pr_review_comments(*, repo: str, pr_number: int) -> list[ReviewComment]:
    result = await async_run(
        args=[
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{pr_number}/comments",
        ],
        timeout=60,
    )
    if result.returncode != 0:
        logger.warning(
            "skipping PR review comments",
            extra={"repo": repo, "pr_number": pr_number, "stderr": result.stderr.strip()},
        )
        return []
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        logger.warning("unparseable review comments", extra={"repo": repo, "pr_number": pr_number})
        return []
    return [
        ReviewComment(
            repo=repo,
            pr_number=pr_number,
            body=item.get("body", "") or "",
            path=item.get("path", "") or "",
            line=item.get("line"),
            author=(item.get("user") or {}).get("login", "") or "",
        )
        for item in payload
    ]


async def get_review_comments(*, repo: str, limit: int = 50) -> Result[list[ReviewComment]]:
    """Fetch inline review comments from recent merged PRs of ``repo``.

    Reuses the project-audit Phase-1 ``gh pr list --state merged`` pattern
    to find PRs, then pulls each PR's review comments. Per-PR failures are
    logged and skipped (fail-soft) so a single bad PR never aborts the run.
    """
    numbers_result = await _merged_pr_numbers(repo=repo, limit=limit)
    if not isinstance(numbers_result, SuccessResult):
        return numbers_result
    comments: list[ReviewComment] = []
    for pr_number in numbers_result.value:
        comments.extend(await _pr_review_comments(repo=repo, pr_number=pr_number))
    return ok(comments)


async def cluster_review_comments(
    *,
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
) -> Result[dict[str, Any]]:
    """Cluster & score review-comment patterns across one or more repos.

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned per repo.
        top_n: Number of top patterns to return.

    Returns:
        ``ok({"patterns": [...], "summary": {...}})`` or ``err(...)``.
    """
    if top_n < 1:
        return err("top_n must be at least 1")

    targets = list(repos) if repos else []
    if not targets:
        detected = await _detect_repo()
        if not detected:
            return err("no repository specified and current repo could not be detected")
        targets = [detected]

    all_comments: list[ReviewComment] = []
    scanned: list[str] = []
    for repo in targets:
        result = await get_review_comments(repo=repo, limit=limit)
        if not isinstance(result, SuccessResult):
            logger.warning("skipping repo", extra={"repo": repo, "error": result.error})
            continue
        all_comments.extend(result.value)
        scanned.append(repo)

    patterns = cluster_and_score(all_comments, top_n=top_n)
    return ok(
        {
            "patterns": [pattern.to_dict() for pattern in patterns],
            "summary": {
                "repos_scanned": scanned,
                "comments_analyzed": len(all_comments),
                "patterns_returned": len(patterns),
                "top_n": top_n,
            },
        }
    )
