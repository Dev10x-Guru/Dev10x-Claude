"""Author reference-rule docs from validated review patterns (GH-349).

Milestone-5 step for the review-bot initiative. Takes the patterns that
:func:`dev10x.github.pattern_validation.validate_candidate_patterns`
(GH-348) marked ``validated`` and renders one reference-rule Markdown
doc per pattern, plus an INDEX-style routing fragment that wires the
generated docs to the review agents.

Like its siblings, this module is **dry-run by default**: the
orchestrator returns the generated doc content and routing fragment for
human review rather than rewriting the canonical
``.claude/rules/INDEX.md`` in place. The optional
:func:`write_rule_docs` helper materializes docs under an explicit base
directory when a caller opts in, keeping file I/O out of the analysis
path and free of hidden CWD coupling.

Internal functions return ``Result[T]`` per ADR-0009; the
``@server.tool()`` boundary calls ``.to_dict()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, SuccessResult, ok
from dev10x.github import pattern_validation

# Generated rule docs live under the review-checks reference tree so the
# review agents (reviewer-generic and friends) pick them up via routing.
GENERATED_RULES_DIR = "references/review-checks/generated"

# Reviewer agent the generated routing rows point at. Review-comment
# patterns are general-purpose checks, so the catch-all reviewer owns
# them until a human re-routes a doc to a more specific agent.
_DEFAULT_REVIEWER = "reviewer-generic"

_SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")


def _rule_slug(signature: str) -> str:
    """Turn a pattern signature into a filename-safe slug."""
    slug = _SLUG_NON_WORD.sub("-", signature.lower()).strip("-")
    return slug or "unnamed-pattern"


def _rule_title(signature: str) -> str:
    cleaned = signature.strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Unnamed pattern"


@dataclass(frozen=True)
class RuleDoc:
    """A generated reference-rule document for one validated pattern."""

    slug: str
    title: str
    path: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "path": self.path,
            "content": self.content,
        }


def render_rule_doc(*, pattern: dict[str, Any]) -> str:
    """Render a single validated pattern into a reference-rule Markdown doc.

    Pure function: takes one entry from
    :func:`pattern_validation.validate_candidate_patterns`' ``validated``
    list and returns the doc body. The confidence note records the
    heuristic provenance so readers do not mistake the frequency/FP
    figures for measured precision.
    """
    signature = pattern.get("signature", "")
    frequency = pattern.get("frequency", 0)
    fp_rate = pattern.get("false_positive_rate", 0.0)
    title = _rule_title(signature)
    tokens = ", ".join(f"`{token}`" for token in signature.split()) or "—"
    return "\n".join(
        [
            f"# {title}",
            "",
            "> Generated from a validated reviewer-comment pattern "
            "(GH-349). The frequency and false-positive rate are "
            "heuristic estimates from recent merged PRs — confirm "
            "against the codebase before enforcing.",
            "",
            "## When this applies",
            "",
            f"Reviewers raised this point **{frequency}** time(s) across "
            "recent merged PRs. Watch for changes whose added lines "
            "match the signal tokens below.",
            "",
            f"**Signal tokens:** {tokens}",
            "",
            "## Confidence",
            "",
            f"- Reviewer frequency: {frequency}",
            f"- Estimated false-positive rate: {fp_rate}",
            "",
            "_Confidence is refined over time via feedback tracking (GH-350)._",
            "",
        ]
    )


def author_rule_docs(*, patterns: list[dict[str, Any]]) -> list[RuleDoc]:
    """Build one :class:`RuleDoc` per validated pattern.

    Pure function: only patterns flagged ``validated`` produce a doc.
    Ordering follows the input (already ranked by the validator).
    """
    docs: list[RuleDoc] = []
    for pattern in patterns:
        if not pattern.get("validated"):
            continue
        signature = pattern.get("signature", "")
        slug = _rule_slug(signature)
        docs.append(
            RuleDoc(
                slug=slug,
                title=_rule_title(signature),
                path=f"{GENERATED_RULES_DIR}/{slug}.md",
                content=render_rule_doc(pattern=pattern),
            )
        )
    return docs


def render_routing_fragment(*, docs: list[RuleDoc]) -> str:
    """Render an INDEX-style routing table fragment for generated docs.

    The fragment is meant to be pasted into ``.claude/rules/INDEX.md`` by
    a human — it is never written in place.
    """
    if not docs:
        return "_No validated patterns — no routing rows generated._"
    rows = ["| Generated rule | Reviewer agent |", "|---|---|"]
    rows.extend(f"| `{doc.path}` | `{_DEFAULT_REVIEWER}` |" for doc in docs)
    return "\n".join(rows)


def write_rule_docs(*, docs: list[RuleDoc], base_dir: Path) -> list[str]:
    """Materialize generated docs under ``base_dir``; return written paths.

    File I/O is isolated here behind an explicit ``base_dir`` so the
    analysis path stays side-effect free and no hidden CWD coupling
    leaks in (GH-979). Each doc's ``path`` is repo-relative; it is
    joined onto ``base_dir`` to form the absolute target.
    """
    written: list[str] = []
    for doc in docs:
        target = base_dir / doc.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.content, encoding="utf-8")
        written.append(str(target))
    return written


async def author_reference_rules(
    *,
    repos: list[str] | None = None,
    limit: int = 50,
    top_n: int = 20,
    diff_limit: int = 20,
    min_frequency: int = 2,
    max_fp_rate: float = 0.5,
) -> Result[dict[str, Any]]:
    """Author reference-rule docs from validated review patterns.

    Orchestrates GH-348 validation, generates a doc per validated
    pattern, and returns the docs plus an INDEX routing fragment. This is
    a dry run — no files are written and no routing table is edited.

    Args:
        repos: ``owner/name`` repositories to analyze. Defaults to the
            current repository when omitted.
        limit: Max merged PRs scanned for review comments.
        top_n: Number of top candidate patterns to consider.
        diff_limit: Max recent merged PRs sampled for diff matching.
        min_frequency: Minimum reviewer frequency for a validated pattern.
        max_fp_rate: Maximum estimated false-positive rate for a
            validated pattern.

    Returns:
        ``ok({"rules": [...], "routing_fragment": str, "summary": {...}})``
        or ``err(...)`` when the upstream validation step fails.
    """
    validated = await pattern_validation.validate_candidate_patterns(
        repos=repos,
        limit=limit,
        top_n=top_n,
        diff_limit=diff_limit,
        min_frequency=min_frequency,
        max_fp_rate=max_fp_rate,
    )
    if not isinstance(validated, SuccessResult):
        return validated

    patterns = validated.value["validated"]
    docs = author_rule_docs(patterns=patterns)
    return ok(
        {
            "rules": [doc.to_dict() for doc in docs],
            "routing_fragment": render_routing_fragment(docs=docs),
            "summary": {
                **validated.value["summary"],
                "rules_authored": len(docs),
                "generated_rules_dir": GENERATED_RULES_DIR,
            },
        }
    )
