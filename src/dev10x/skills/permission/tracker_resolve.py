"""Resolve the project's issue tracker for permission seeding (GH-768).

The durable answer lives in the matching ``projects[]`` entry of
``~/.config/Dev10x/friction.yaml`` under the ``tracker`` key, falling
back to its ``defaults:`` block — the same first-match-wins resolution
every other durable pref uses (ADR-0018 D4), so one answer covers a
repo and every worktree of it.

Absent any answer the resolution degrades to :meth:`Tracker.default`
(``linear``), which reproduces the pre-GH-768 unconditional behaviour.
That matters for upgrades: a user who never runs the onboarding gate
keeps exactly the rules they had, rather than silently losing their
tracker's allows on the next ``ensure-base``.
"""

from __future__ import annotations

import logging

from dev10x.domain.common.tracker_choice import Tracker, parse_tracker
from dev10x.domain.documents.session_yaml import FrictionYamlDocument

log = logging.getLogger(__name__)


def resolve_tracker(*, toplevel: str | None) -> Tracker:
    """The tracker configured for ``toplevel``, else the default."""
    if not toplevel:
        return Tracker.default()
    document = FrictionYamlDocument(toplevel=toplevel)
    matched = document.matched() or {}
    tracker = parse_tracker(matched.get("tracker"))
    if tracker is not None:
        return tracker
    tracker = parse_tracker(document.defaults().get("tracker"))
    if tracker is not None:
        return tracker
    return Tracker.default()


def tracker_source(*, toplevel: str | None) -> str:
    """Where the resolved tracker came from — for the seeding report.

    Seeding silently omitting ~35 rules is exactly the kind of change a
    user needs told, so the caller can say *why* only one tracker's
    block was applied instead of leaving them to infer it.
    """
    if not toplevel:
        return "default"
    document = FrictionYamlDocument(toplevel=toplevel)
    if parse_tracker((document.matched() or {}).get("tracker")) is not None:
        return "project"
    if parse_tracker(document.defaults().get("tracker")) is not None:
        return "defaults"
    return "default"


__all__ = ["resolve_tracker", "tracker_source"]
