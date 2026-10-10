"""Profile tier enum for validator registry.

Replaces the `PROFILE_HIERARCHY` tuple + ordinal `index()` compare +
`except ValueError` fallback with a type-safe IntEnum. `MINIMAL < STANDARD
< STRICT` is intrinsic; invalid raw strings are rejected at parse time
via `from_raw`, which collapses the "unknown profile → default" fallback
to one place.
"""

from __future__ import annotations

from enum import IntEnum


class ProfileTier(IntEnum):
    """Active profile filter for Bash command validators (GH-413).

    Lower-tier validators run at all higher tiers (a `MINIMAL` rule fires
    under `STANDARD` and `STRICT`; a `STRICT` rule does not fire under
    `STANDARD`).
    """

    MINIMAL = 0
    STANDARD = 1
    STRICT = 2

    @classmethod
    def default(cls) -> ProfileTier:
        return cls.STANDARD

    @classmethod
    def from_raw(cls, raw: str | None) -> ProfileTier:
        """Parse a raw string from env or YAML into a ProfileTier.

        Unknown / empty values fall back to ``ProfileTier.default()``.
        Case-insensitive; trims surrounding whitespace.
        """
        if not raw:
            return cls.default()
        normalized = raw.strip().lower()
        for member in cls:
            if member.name.lower() == normalized:
                return member
        return cls.default()

    def includes(self, validator_tier: ProfileTier) -> bool:
        """Return True if a validator at ``validator_tier`` runs at this tier."""
        return validator_tier <= self


__all__ = ["ProfileTier"]
