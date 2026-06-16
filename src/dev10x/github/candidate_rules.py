"""Render a read-only candidate-rules report (GH-347).

MVP visibility step for the review-bot initiative: takes the recurring
review-comment patterns mined by
:func:`dev10x.github.review_patterns.cluster_review_comments` (GH-346)
and formats them into a human-readable Markdown memo.

This report is intentionally **read-only**. It surfaces what reviewers
repeat so a human can decide what deserves a rule — it does NOT generate,
write, or apply any permission rule. Rule generation is deferred to a
later initiative step.

Internal functions return ``Result[T]`` per ADR-0009; the
``@server.tool()`` boundary calls ``.to_dict()``.
"""

from __future__ import annotations

import re
from typing import Any

from dev10x.domain.common.result import Result, SuccessResult, ok
from dev10x.github import review_patterns

# Max characters kept from an example comment in the memo. Examples are a
# readability aid, not the full comment — long bodies are truncated.
_EXAMPLE_LIMIT = 120

_WHITESPACE = re.compile(r"\s+")

_READ_ONLY_NOTE = (
    "> Read-only visibility memo (MVP). These are the most frequently "
    "recurring reviewer comments across recent merged PRs. **No rules were "
    "generated, written, or applied** — this report only surfaces candidates "
    "for human review."
)


def _summarize_example(body: str) -> str:
    """Collapse whitespace and truncate a comment body for the memo."""
    collapsed = _WHITESPACE.sub(" ", body).strip()
    if len(collapsed) <= _EXAMPLE_LIMIT:
        return collapsed
    return collapsed[: _EXAMPLE_LIMIT - 1].rstrip() + "…"


def _join_or_dash(values: list[str]) -> str:
    return ", ".join(values) if values else "—"


def render_report(*, patterns: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """Format clustered patterns into a read-only Markdown memo.

    Pure function: takes the ``patterns`` / ``summary`` payload produced by
    :func:`review_patterns.cluster_review_comments` and returns the memo
    text. Patterns are assumed pre-sorted (frequency desc) by the miner.
    """
    scanned = summary.get("repos_scanned", [])
    lines = [
        "# Candidate Rules Report",
        "",
        _READ_ONLY_NOTE,
        "",
        f"**Repositories scanned:** {_join_or_dash(scanned)}",
        f"**Merged-PR review comments analyzed:** {summary.get('comments_analyzed', 0)}",
        f"**Candidate patterns (top {summary.get('top_n', 0)}):** "
        f"{summary.get('patterns_returned', len(patterns))}",
        "",
        "## Top candidate patterns",
        "",
    ]

    if not patterns:
        lines.append(
            "_No recurring patterns found — every analyzed comment was unique "
            "or contained only code/links._"
        )
        return "\n".join(lines)

    for rank, pattern in enumerate(patterns, start=1):
        frequency = pattern.get("frequency", 0)
        plural = "occurrence" if frequency == 1 else "occurrences"
        lines.append(f"### {rank}. `{pattern.get('signature', '')}` — {frequency} {plural}")
        lines.append("")
        lines.append(f"- **Files:** {_join_or_dash(pattern.get('files', []))}")
        lines.append(f"- **Authors:** {_join_or_dash(pattern.get('authors', []))}")
        examples = pattern.get("examples", [])
        if examples:
            lines.append(f"- **Example:** {_summarize_example(examples[0])}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def candidate_rules_report(
    *,
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
) -> Result[dict[str, Any]]:
    """Produce a read-only candidate-rules report for one or more repos.

    Orchestrates the GH-346 miner and renders its output into a memo. No
    rules are generated — see the module docstring.

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned per repo.
        top_n: Number of top patterns to include in the report.

    Returns:
        ``ok({"report": str, "patterns": [...], "summary": {...}})`` or
        ``err(...)`` when the underlying mining step fails.
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
    return ok(
        {
            "report": render_report(patterns=patterns, summary=summary),
            "patterns": patterns,
            "summary": summary,
        }
    )
