"""Session policy rules — pure decisions owned by the domain core.

These were previously defined in ``dev10x.hooks.session_policy``, which
forced ``session.queries`` to defer its imports into function bodies to
break the cycle ``hooks.session_dispatch → session.queries →
hooks.session_policy`` (audit memo Findings I2 + I10). Both rules depend
only on ``domain/`` types, so they belong in the core: adapters now
import them inward instead of reaching up into ``hooks/``.

See ADR-0008 (context boundary protocol) for the dependency-direction
rule and ADR-0007 for the Policy Rule archetype these satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.documents.session_state import PlanSummary
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.rules.policy_rule import PolicyRule


class UnknownFrictionLevelError(ValueError):
    """Raised when decision guidance is asked to format an unknown friction level."""


@dataclass(frozen=True)
class ReadFrictionLevelRule(PolicyRule[FrictionLevel]):
    """Read the friction level from ``.claude/Dev10x/session.yaml``.

    Returns ``FrictionLevel.default()`` when the file is missing or
    unreadable — that is the soft fallback. Use ``DecisionGuidanceRule``
    for strict behaviour at format time.
    """

    toplevel: str

    def apply(self) -> FrictionLevel:
        session_yaml = Path(self.toplevel) / ".claude" / "Dev10x" / "session.yaml"
        if not session_yaml.exists():
            return FrictionLevel.default()
        try:
            import yaml

            with open(session_yaml) as f:
                data = yaml.safe_load(f) or {}
            return FrictionLevel.from_yaml(data.get("friction_level"))
        except Exception:
            return FrictionLevel.default()


@dataclass(frozen=True)
class DecisionGuidanceRule(PolicyRule[str]):
    """Format resume guidance for the agent based on plan + friction level.

    Raises ``UnknownFrictionLevelError`` when ``friction_level`` is not
    a recognised :class:`FrictionLevel` member. Audit M7 #D2 calls out
    the prior fall-through (which silently produced strict-style guidance
    for adaptive sessions) as a latent bug.
    """

    plan: dict[str, Any]
    friction_level: FrictionLevel

    def apply(self) -> str:
        if not isinstance(self.friction_level, FrictionLevel):
            raise UnknownFrictionLevelError(f"Unknown friction level: {self.friction_level!r}")

        summary = PlanSummary.from_dict(data=self.plan)
        if not summary.pending_decisions:
            if summary.has_remaining_tasks:
                return "Session resumed with tasks remaining. Auto-advance through the task list."
            return ""

        return self.friction_level.pending_decisions_guidance()


__all__ = [
    "UnknownFrictionLevelError",
    "ReadFrictionLevelRule",
    "DecisionGuidanceRule",
]
