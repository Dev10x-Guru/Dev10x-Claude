"""Validate candidate review-comment patterns against recent diffs (GH-348).

Milestone-5 step for the review-bot initiative. Takes the recurring
review-comment patterns mined by
:func:`dev10x.github.review_patterns.cluster_review_comments` (GH-346)
and estimates, for each pattern, how often it would fire on recent code
changes — a heuristic false-positive proxy used to decide which patterns
are worth turning into reference rules (GH-349).

The false-positive rate here is a **heuristic estimate, not a measured
ground truth**: it assumes that a pattern firing on many more diffs than
the number of review comments that formed it is likely to over-trigger
as a rule. Treat the ``validated`` flag and ranking as guidance for
human rule authoring, not as a precise metric.

Like :mod:`dev10x.github.review_patterns`, this module is intentionally
self-contained — it fetches its own diffs via ``gh`` rather than
reaching into the miner's private helpers. It is wired as the
``validate_candidate_patterns`` MCP tool in ``github_tools.py``.

Internal functions return ``Result[T]`` per ADR-0009; the
``@server.tool()`` boundary calls ``.to_dict()``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.github import review_patterns
from dev10x.subprocess_utils import async_run

logger = logging.getLogger(__name__)

# A pattern fires on a diff when at least this fraction of its signature
# tokens appear among the diff's added-line tokens. Kept below 1.0 so a
# 6-token signature still matches when most (not all) tokens are present.
_MATCH_THRESHOLD = 0.6

# Defaults for the validated / rejected decision. A pattern is validated
# when reviewers raised it at least ``_DEFAULT_MIN_FREQUENCY`` times and
# its estimated false-positive rate stays at or below
# ``_DEFAULT_MAX_FP_RATE``.
_DEFAULT_MIN_FREQUENCY = 2
_DEFAULT_MAX_FP_RATE = 0.5

# Recent merged PRs sampled for diff matching when not overridden.
_DEFAULT_DIFF_LIMIT = 20

_NON_WORD = re.compile(r"[^a-z0-9_\s]")


def _added_line_tokens(diff_text: str) -> set[str]:
    """Collect lowercased word tokens from a unified diff's added lines.

    Only ``+`` hunk lines (excluding the ``+++`` file header) contribute,
    so the token set reflects newly written code rather than context or
    removals.
    """
    tokens: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            cleaned = _NON_WORD.sub(" ", line[1:].lower())
            tokens.update(token for token in cleaned.split() if token)
    return tokens


def pattern_fires(
    *,
    signature: str,
    diff_tokens: set[str],
    threshold: float = _MATCH_THRESHOLD,
) -> bool:
    """Return whether a pattern signature fires on a diff's added tokens.

    The signature is already stopword-free (the GH-346 miner strips
    stopwords before building it), so a plain intersection ratio against
    the diff's added-line tokens is enough. An empty signature never
    fires.
    """
    signature_tokens = {token for token in signature.split() if token}
    if not signature_tokens:
        return False
    overlap = len(signature_tokens & diff_tokens)
    return overlap / len(signature_tokens) >= threshold


def estimate_false_positive_rate(*, frequency: int, diff_matches: int) -> float:
    """Heuristic FP proxy: surplus diff matches beyond reviewer frequency.

    A pattern that fires on many more diffs than the number of review
    comments that formed it is likely to over-trigger as a rule, so the
    surplus is treated as the probable false-positive surface. When the
    pattern fires on no diffs we cannot estimate a rate and return
    ``0.0`` — but such a pattern is also a weak rule candidate, which
    :func:`validate_patterns` reflects via its ``diff_matches`` count.
    """
    if diff_matches <= 0:
        return 0.0
    surplus = max(0, diff_matches - frequency)
    return surplus / diff_matches


@dataclass(frozen=True)
class ValidatedPattern:
    """A candidate pattern scored against recent diffs."""

    signature: str
    frequency: int
    diff_matches: int
    false_positive_rate: float
    validated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "frequency": self.frequency,
            "diff_matches": self.diff_matches,
            "false_positive_rate": round(self.false_positive_rate, 4),
            "validated": self.validated,
        }


def validate_patterns(
    *,
    patterns: list[dict[str, Any]],
    diffs: list[str],
    min_frequency: int = _DEFAULT_MIN_FREQUENCY,
    max_fp_rate: float = _DEFAULT_MAX_FP_RATE,
    threshold: float = _MATCH_THRESHOLD,
) -> list[ValidatedPattern]:
    """Score each candidate pattern against a corpus of recent diffs.

    Pure function: takes the ``patterns`` payload from
    :func:`review_patterns.cluster_review_comments` and a list of unified
    diff texts, and returns a per-pattern verdict. Ordering is
    deterministic: validated patterns first, then false-positive rate
    ascending, then frequency descending, then signature ascending.
    """
    diff_token_sets = [_added_line_tokens(diff) for diff in diffs]
    results: list[ValidatedPattern] = []
    for pattern in patterns:
        signature = pattern.get("signature", "")
        frequency = pattern.get("frequency", 0)
        diff_matches = sum(
            1
            for tokens in diff_token_sets
            if pattern_fires(signature=signature, diff_tokens=tokens, threshold=threshold)
        )
        fp_rate = estimate_false_positive_rate(frequency=frequency, diff_matches=diff_matches)
        validated = frequency >= min_frequency and fp_rate <= max_fp_rate
        results.append(
            ValidatedPattern(
                signature=signature,
                frequency=frequency,
                diff_matches=diff_matches,
                false_positive_rate=fp_rate,
                validated=validated,
            )
        )
    results.sort(key=lambda v: (not v.validated, v.false_positive_rate, -v.frequency, v.signature))
    return results


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


async def _pr_diff(*, repo: str, pr_number: int) -> str | None:
    result = await async_run(
        args=["gh", "pr", "diff", str(pr_number), "--repo", repo],
        timeout=60,
    )
    if result.returncode != 0:
        logger.warning(
            "skipping PR diff",
            extra={"repo": repo, "pr_number": pr_number, "stderr": result.stderr.strip()},
        )
        return None
    return result.stdout or ""


async def _recent_diffs(*, repo: str, limit: int) -> list[str]:
    numbers_result = await _merged_pr_numbers(repo=repo, limit=limit)
    if not isinstance(numbers_result, SuccessResult):
        logger.warning("skipping repo diffs", extra={"repo": repo, "error": numbers_result.error})
        return []
    diffs: list[str] = []
    for pr_number in numbers_result.value:
        diff = await _pr_diff(repo=repo, pr_number=pr_number)
        if diff:
            diffs.append(diff)
    return diffs


async def validate_candidate_patterns(
    *,
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
    diff_limit: int = _DEFAULT_DIFF_LIMIT,
    min_frequency: int = _DEFAULT_MIN_FREQUENCY,
    max_fp_rate: float = _DEFAULT_MAX_FP_RATE,
) -> Result[dict[str, Any]]:
    """Validate mined patterns against recent merged-PR diffs.

    Orchestrates the GH-346 miner, fetches recent merged-PR diffs from
    the same repositories, and scores each pattern. No rules are
    generated — that is GH-349's job.

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned for review comments (miner input).
        top_n: Number of top candidate patterns to validate.
        diff_limit: Max recent merged PRs sampled for diff matching.
        min_frequency: Minimum reviewer frequency for a validated pattern.
        max_fp_rate: Maximum estimated false-positive rate for a
            validated pattern.

    Returns:
        ``ok({"validated": [...], "summary": {...}})`` or ``err(...)``
        when the underlying mining step fails.
    """
    mined = await review_patterns.cluster_review_comments(
        repos=repos,
        limit=limit,
        top_n=top_n,
    )
    if not isinstance(mined, SuccessResult):
        return mined

    patterns = mined.value["patterns"]
    summary = mined.value["summary"]
    scanned = summary.get("repos_scanned", [])

    diffs: list[str] = []
    for repo in scanned:
        diffs.extend(await _recent_diffs(repo=repo, limit=diff_limit))

    validated = validate_patterns(
        patterns=patterns,
        diffs=diffs,
        min_frequency=min_frequency,
        max_fp_rate=max_fp_rate,
    )
    return ok(
        {
            "validated": [pattern.to_dict() for pattern in validated],
            "summary": {
                **summary,
                "diffs_analyzed": len(diffs),
                "validated_count": sum(1 for pattern in validated if pattern.validated),
                "min_frequency": min_frequency,
                "max_fp_rate": max_fp_rate,
            },
        }
    )
