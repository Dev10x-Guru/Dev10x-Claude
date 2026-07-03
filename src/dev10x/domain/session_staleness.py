"""``session_stale`` predicate — the GH-742 F1 enforcement seam (ADR-0016).

A new invocation must not blindly adopt a persisted ``session.yaml``: the
stale-config auto-merge of PR #740 (GH-742) happened because a leftover
``solo_maintainer: true`` from an unrelated session was trusted wholesale.
The ``session_adoption`` gate keys on this predicate via
``auto-advance-if-stale-free`` — a fresh session auto-advances, a stale
one re-prompts.

The predicate is pure (ADR-0007 D3): the caller supplies the persisted
identity and the current invocation's identity; file/git reads happen at
the infra tier.
"""

from __future__ import annotations

from collections.abc import Sequence


def session_stale(
    *,
    recorded_branch: str | None,
    current_branch: str | None,
    recorded_tickets: Sequence[str] = (),
    current_tickets: Sequence[str] = (),
) -> bool:
    """Return ``True`` when the persisted session mismatches this invocation.

    Freshness requires *positive* evidence that the persisted file belongs
    to the current invocation — a matching branch or an overlapping ticket.
    Absent that evidence (no recorded identity, a mismatched branch, or
    disjoint tickets), the session is treated as stale. This mirrors the
    ``GateContext`` convention that unknown staleness resolves in the safe
    direction (ADR-0016).
    """
    recorded_b = (recorded_branch or "").strip()
    current_b = (current_branch or "").strip()
    if recorded_b and current_b and recorded_b == current_b:
        return False

    recorded_t = {ticket for ticket in recorded_tickets if ticket}
    current_t = {ticket for ticket in current_tickets if ticket}
    if recorded_t and current_t and not recorded_t.isdisjoint(current_t):
        return False

    return True


__all__ = ["session_stale"]
