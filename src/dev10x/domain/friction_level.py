"""Friction level enum — how aggressively a session pauses for confirmation.

Replaces scattered string-equality checks (``friction_level == "adaptive"``,
``== "guided"``) across hooks, validators, and commands with a single
type-safe enum and a stable parser.

Note: shares the ``STRICT`` member name with ``ProfileTier`` but the two
enums are unrelated. ``ProfileTier`` controls *which validators run*;
``FrictionLevel`` controls *how the work-on orchestrator paces itself*.
Keep type imports explicit at every use site.
"""

from __future__ import annotations

from enum import StrEnum


class FrictionLevel(StrEnum):
    """Session friction setting from ``.claude/Dev10x/session.yaml``.

    Members preserve the lowercase string value so YAML round-trips and
    legacy ``friction_level`` columns continue to read cleanly.
    """

    STRICT = "strict"
    GUIDED = "guided"
    ADAPTIVE = "adaptive"

    @classmethod
    def default(cls) -> FrictionLevel:
        """Internal default — matches the long-standing string fallback ("strict").

        The interactive ``Dev10x:init`` prompt suggests ``guided`` for new
        projects, but internal code paths (Config dataclass, YAML parse
        fallbacks) all defaulted to ``strict`` before this enum existed.
        Preserving that here keeps the type migration behaviour-neutral.
        """
        return cls.STRICT

    @classmethod
    def from_yaml(cls, raw: object) -> FrictionLevel:
        """Parse a raw YAML value into a FrictionLevel.

        Empty/unknown/non-string values fall back to ``FrictionLevel.default()``.
        Case-insensitive; trims surrounding whitespace.
        """
        if not isinstance(raw, str):
            return cls.default()
        normalized = raw.strip().lower()
        if not normalized:
            return cls.default()
        for member in cls:
            if member.value == normalized:
                return member
        return cls.default()

    def pending_decisions_guidance(self) -> str:
        """Return the session-resume instruction for pending-decision state.

        Called by ``DecisionGuidanceRule`` when the plan has one or more
        unresolved decision tasks.  Each member encodes its own pacing
        rule, eliminating the if/elif dispatch from the rule body.

        Returns:
            A non-empty instruction string for every recognised member.
        """
        if self is FrictionLevel.ADAPTIVE:
            return (
                "Session resumed with pending decisions. Friction level is adaptive — "
                "auto-select recommended options for all queued decisions and continue "
                "advancing through the task list without calling AskUserQuestion."
            )
        return (
            "Session resumed with pending decisions. "
            "Re-ask each pending decision using AskUserQuestion — "
            "invoke Dev10x:ask before advancing."
        )

    def fallback_guidance(self, *, fallback: str) -> str:
        """Return a friction-level-specific fallback clause for block messages.

        In GUIDED mode the agent is shown a concrete fallback path (skill
        guardrails to apply manually, or an MCP-unavailability escape).
        In STRICT and ADAPTIVE modes the block is unadorned — the fallback
        text is omitted so the message stays concise.

        Args:
            fallback: The fallback snippet to surface in GUIDED mode.
                      May be an MCP-server fallback description, a manual-
                      guardrail list, or any other escape-hatch hint.

        Returns:
            The fallback clause (including a leading newline) when GUIDED,
            or an empty string for other levels.
        """
        if self is FrictionLevel.GUIDED:
            return fallback
        return ""


__all__ = ["FrictionLevel"]
