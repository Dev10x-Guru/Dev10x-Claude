"""TicketId value object — canonical `[A-Z]+-\\d+` ticket identifier.

Eliminates duplicate regex literals previously scattered across
`validators/commit_jtbd.py`, `skills/release/collect_prs.py`, and
`skills/permission/merge_worktree_permissions.py` (audit finding
C1 — 2026-05-18; also resolves I5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TICKET_ID_PATTERN = r"[A-Z]+-\d+"
_FULL_RE = re.compile(rf"^{TICKET_ID_PATTERN}$")
_SEARCH_RE = re.compile(TICKET_ID_PATTERN)


@dataclass(frozen=True)
class TicketId:
    project: str
    number: int

    def __str__(self) -> str:
        return f"{self.project}-{self.number}"

    @classmethod
    def parse(cls, value: str) -> TicketId:
        if not isinstance(value, str) or not _FULL_RE.match(value):
            msg = f"Invalid ticket id: {value!r}. Expected '[A-Z]+-<digits>'."
            raise ValueError(msg)
        project, number = value.rsplit("-", 1)
        return cls(project=project, number=int(number))

    @classmethod
    def try_parse(cls, value: str) -> TicketId | None:
        try:
            return cls.parse(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def find_first(cls, text: str) -> TicketId | None:
        match = _SEARCH_RE.search(text)
        if not match:
            return None
        return cls.try_parse(match.group(0))

    @classmethod
    def find_all(cls, text: str) -> list[TicketId]:
        return [
            ticket
            for match in _SEARCH_RE.finditer(text)
            if (ticket := cls.try_parse(match.group(0))) is not None
        ]
