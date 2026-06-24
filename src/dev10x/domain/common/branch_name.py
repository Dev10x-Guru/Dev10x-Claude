"""BranchName value object — `username/TICKET-ID/[worktree/]slug` convention.

The branch-naming convention is documented in .claude/rules but
enforced nowhere. This value object provides parsing,
convention validation, and protected-branch detection so MCP
entry points and git helpers can validate inputs at the
boundary. Audit finding C10 — 2026-05-18.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dev10x.domain.common.ticket_id import TicketId

# Base-branch detection priority — first existing branch wins. The
# protected-branch set is exactly these names (membership, order-free).
BASE_BRANCH_PRIORITY: tuple[str, ...] = ("develop", "development", "main", "master", "trunk")

PROTECTED_BRANCHES: frozenset[str] = frozenset(BASE_BRANCH_PRIORITY)

# Slug constraints — lower-case alphanumerics with hyphens/underscores.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class BranchName:
    raw: str
    username: str | None = None
    ticket: TicketId | None = None
    worktree: str | None = None
    slug: str | None = None

    def __str__(self) -> str:
        return self.raw

    @property
    def is_protected(self) -> bool:
        return self.raw in PROTECTED_BRANCHES

    @property
    def follows_convention(self) -> bool:
        return self.username is not None and self.ticket is not None and self.slug is not None

    @classmethod
    def parse(cls, value: str) -> BranchName:
        if not isinstance(value, str) or not value:
            raise ValueError(f"Invalid branch name: {value!r}")
        parts = value.split("/")
        if len(parts) < 3 or len(parts) > 4:
            return cls(raw=value)

        username = parts[0]
        ticket_str = parts[1]
        if not _USERNAME_RE.match(username):
            return cls(raw=value)
        ticket = TicketId.try_parse(ticket_str)
        if ticket is None:
            return cls(raw=value)

        if len(parts) == 3:
            slug = parts[2]
            worktree = None
        else:
            worktree = parts[2]
            slug = parts[3]

        if not _SLUG_RE.match(slug):
            return cls(raw=value)
        if worktree is not None and not _SLUG_RE.match(worktree):
            return cls(raw=value)

        return cls(
            raw=value,
            username=username,
            ticket=ticket,
            worktree=worktree,
            slug=slug,
        )

    @classmethod
    def try_parse(cls, value: str) -> BranchName | None:
        try:
            return cls.parse(value)
        except (TypeError, ValueError):
            return None
