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
# A ticket occupying a whole branch-path segment, e.g. ``user/GH-12/slug``.
# Case-insensitive so lowercase branch names (``gh-12``) still resolve; the
# ``GH-`` prefix needs no special case — it is already a ``[A-Z]+`` project.
_BRANCH_RE = re.compile(rf"(?:^|/)({TICKET_ID_PATTERN})(?:/|$)", re.IGNORECASE)
# A leading ``<ticket-id> `` prefix to strip from a commit description.
_LEADING_RE = re.compile(rf"^{TICKET_ID_PATTERN}\s+")


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
    def find_first_in_branch_name(cls, branch: str) -> TicketId | None:
        """Return the ticket id occupying a full branch-path segment.

        Matches case-insensitively and only when the id is bounded by
        path separators or the string ends (``user/GH-12/slug``), so an
        unrelated number in a slug is not picked up. Lowercase branch
        names are normalised to the canonical upper-case form.
        """
        match = _BRANCH_RE.search(branch)
        if not match:
            return None
        return cls.try_parse(match.group(1).upper())

    @classmethod
    def strip_leading(cls, text: str) -> str:
        """Remove a leading ``<ticket-id> `` prefix (id plus whitespace)."""
        return _LEADING_RE.sub("", text)
