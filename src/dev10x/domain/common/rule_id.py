"""RuleId value object — canonical ``DX\\d{3}`` validator rule identifier.

``rule_id`` was a raw ``str`` everywhere in the validator subsystem: the
``ValidatorBase`` default was ``""``, nothing rejected a typo like
``"DX42"``, and four registry lookups case-folded with an inline
``.upper()`` on every call (audit finding GH-510 — 2026-06-10).

This object owns the format contract (``^DX\\d{3}$``) and case
normalisation. ``ValidatorSpec`` runs every ``rule_id`` through
:meth:`parse` at construction, so a malformed id fails fast at registry
build time rather than silently mismatching an assertion later.

Note: this VO governs the validator ``DXNNN`` namespace only. The
unrelated ``rule_id`` on ``skills/audit/cli_friction.Rule`` (values like
``"raw-gh-pr"``) is a different concept and is intentionally untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RULE_ID_PATTERN = r"DX\d{3}"
_CANONICAL_RE = re.compile(rf"^{RULE_ID_PATTERN}$")
_PARSE_RE = re.compile(rf"^{RULE_ID_PATTERN}$", re.IGNORECASE)


@dataclass(frozen=True)
class RuleId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _CANONICAL_RE.match(self.value):
            msg = f"Invalid rule id: {self.value!r}. Expected canonical 'DXNNN'."
            raise ValueError(msg)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str) -> RuleId:
        if not isinstance(value, str) or not _PARSE_RE.match(value):
            msg = f"Invalid rule id: {value!r}. Expected 'DX' followed by 3 digits."
            raise ValueError(msg)
        return cls(value.upper())

    @classmethod
    def try_parse(cls, value: str) -> RuleId | None:
        try:
            return cls.parse(value)
        except (TypeError, ValueError):
            return None
