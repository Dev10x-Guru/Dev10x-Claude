"""Confidence weighting & feedback tracking for review rules (GH-350).

Final milestone-5 step for the review-bot initiative. Records, per rule,
how often it caught a real issue versus fired as a false positive, then
ranks rules by a Wilson-score confidence so the highest-precision rules
surface first and noisy ones sink.

The Wilson lower bound rewards evidence: a rule with 5 catches / 0 false
positives outranks one with 1 catch / 0 false positives even though both
have raw precision 1.0. A rule with no feedback yet scores 0.0.

Feedback persists as a small JSON store. Low-level helpers take an
explicit ``store_path`` so file I/O carries no hidden CWD coupling
(GH-979); the orchestrators resolve a default under the Dev10x config
home when no path is given.

Internal functions return ``Result[T]`` per ADR-0009; the
``@server.tool()`` boundary calls ``.to_dict()``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir

_FEEDBACK_FILENAME = "rule-feedback.json"

# z-score for a 95% Wilson score interval.
_WILSON_Z = 1.96

CATCH = "catch"
FALSE_POSITIVE = "false_positive"
_OUTCOMES = frozenset({CATCH, FALSE_POSITIVE})


@dataclass(frozen=True)
class RuleFeedback:
    """Catch/false-positive tallies for one rule."""

    rule_id: str
    catches: int = 0
    false_positives: int = 0

    @property
    def total(self) -> int:
        return self.catches + self.false_positives

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "catches": self.catches,
            "false_positives": self.false_positives,
        }


def confidence_score(*, catches: int, false_positives: int) -> float:
    """Wilson lower bound of precision (catches / total) at 95%.

    Returns ``0.0`` when there is no feedback yet.
    """
    total = catches + false_positives
    if total <= 0:
        return 0.0
    phat = catches / total
    z = _WILSON_Z
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


@dataclass(frozen=True)
class ScoredRule:
    """A rule with its confidence score, ready for ranking."""

    rule_id: str
    catches: int
    false_positives: int
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "catches": self.catches,
            "false_positives": self.false_positives,
            "confidence": round(self.confidence, 4),
        }


def rank_rules(*, feedback: list[RuleFeedback]) -> list[ScoredRule]:
    """Score each rule and rank by confidence desc, catches desc, id asc."""
    scored = [
        ScoredRule(
            rule_id=item.rule_id,
            catches=item.catches,
            false_positives=item.false_positives,
            confidence=confidence_score(
                catches=item.catches,
                false_positives=item.false_positives,
            ),
        )
        for item in feedback
    ]
    scored.sort(key=lambda rule: (-rule.confidence, -rule.catches, rule.rule_id))
    return scored


def load_feedback(*, store_path: Path) -> dict[str, RuleFeedback]:
    """Load the feedback store; an absent file is an empty store."""
    if not store_path.exists():
        return {}
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    return {
        rule_id: RuleFeedback(
            rule_id=rule_id,
            catches=int(entry.get("catches", 0)),
            false_positives=int(entry.get("false_positives", 0)),
        )
        for rule_id, entry in raw.items()
    }


def save_feedback(*, feedback: dict[str, RuleFeedback], store_path: Path) -> None:
    """Persist the feedback store as sorted, indented JSON."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        rule_id: {"catches": item.catches, "false_positives": item.false_positives}
        for rule_id, item in feedback.items()
    }
    store_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def record_feedback(*, rule_id: str, outcome: str, store_path: Path) -> RuleFeedback:
    """Increment a rule's catch or false-positive tally and persist it.

    Raises ``ValueError`` on an unknown outcome so direct callers fail
    loud; the MCP orchestrator validates first and returns an error
    result instead.
    """
    if outcome not in _OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; expected one of {sorted(_OUTCOMES)}")
    feedback = load_feedback(store_path=store_path)
    current = feedback.get(rule_id, RuleFeedback(rule_id=rule_id))
    if outcome == CATCH:
        updated = RuleFeedback(
            rule_id=rule_id,
            catches=current.catches + 1,
            false_positives=current.false_positives,
        )
    else:
        updated = RuleFeedback(
            rule_id=rule_id,
            catches=current.catches,
            false_positives=current.false_positives + 1,
        )
    feedback[rule_id] = updated
    save_feedback(feedback=feedback, store_path=store_path)
    return updated


def _default_store_path() -> Path:
    return Dev10xConfigDir.home() / _FEEDBACK_FILENAME


def _resolve_store_path(store_path: str | None) -> Path:
    return Path(store_path) if store_path else _default_store_path()


async def rule_confidence_report(*, store_path: str | None = None) -> Result[dict[str, Any]]:
    """Rank tracked rules by confidence.

    Args:
        store_path: Feedback JSON store. Defaults to the Dev10x config
            home when omitted.

    Returns:
        ``ok({"ranked": [...], "summary": {...}})``.
    """
    path = _resolve_store_path(store_path)
    feedback = load_feedback(store_path=path)
    ranked = rank_rules(feedback=list(feedback.values()))
    return ok(
        {
            "ranked": [rule.to_dict() for rule in ranked],
            "summary": {"rules_tracked": len(ranked), "store_path": str(path)},
        }
    )


async def record_rule_feedback(
    *,
    rule_id: str,
    outcome: str,
    store_path: str | None = None,
) -> Result[dict[str, Any]]:
    """Record one catch or false-positive for a rule.

    Args:
        rule_id: Identifier of the rule that fired.
        outcome: ``"catch"`` (real issue) or ``"false_positive"``.
        store_path: Feedback JSON store. Defaults to the Dev10x config
            home when omitted.

    Returns:
        ``ok({"feedback": {...}})`` or ``err(...)`` on an unknown outcome.
    """
    if outcome not in _OUTCOMES:
        return err(f"unknown outcome {outcome!r}; expected one of {sorted(_OUTCOMES)}")
    path = _resolve_store_path(store_path)
    updated = record_feedback(rule_id=rule_id, outcome=outcome, store_path=path)
    return ok({"feedback": updated.to_dict()})
