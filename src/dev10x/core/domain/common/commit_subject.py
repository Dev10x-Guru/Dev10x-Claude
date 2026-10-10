"""CommitSubject value object — parse a ``<gitmoji> <ticket> <desc>`` title.

The commit-title prefix structure (a leading gitmoji, an optional ticket
id, then the description) was peeled apart by two near-identical helpers
in ``validators/commit_jtbd.py`` — one returning the gitmoji, one
returning the remaining description — that each re-scanned the leading
non-ASCII run (audit finding GH-523-A — 2026-06-10).

This object parses a title once into its three parts. Ticket handling
delegates to :class:`TicketId`. The JTBD Job-Story prose grammar in
``skills/common/jtbd.py`` is a different concept (it parses a
``**When** ... **I want to** ...`` sentence, not a commit title) and is
intentionally left separate.
"""

from __future__ import annotations

from dataclasses import dataclass

from dev10x.domain.common.ticket_id import TicketId


@dataclass(frozen=True)
class CommitSubject:
    gitmoji: str
    ticket: TicketId | None
    description: str

    @classmethod
    def parse(cls, title: str) -> CommitSubject:
        cut = 0
        while cut < len(title) and not title[cut].isascii():
            cut += 1
        gitmoji = title[:cut].strip()
        rest = title[cut:].strip()
        first_token = rest.split(maxsplit=1)[0] if rest else ""
        ticket = TicketId.try_parse(first_token)
        description = TicketId.strip_leading(rest).strip()
        return cls(gitmoji=gitmoji, ticket=ticket, description=description)
