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


__all__ = ["FrictionLevel"]
