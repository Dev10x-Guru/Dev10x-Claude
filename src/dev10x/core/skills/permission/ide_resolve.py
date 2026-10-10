"""Resolve the project's IDE MCP server for permission seeding (GH-1261).

The durable answer lives in the matching ``projects[]`` entry of
``~/.config/Dev10x/friction.yaml`` under the ``ide`` key, falling back to
its ``defaults:`` block — the same first-match-wins resolution every
other durable pref uses (ADR-0018 D4), so one answer covers a repo and
every worktree of it.

Absent any answer the resolution degrades to :meth:`Ide.default`
(``none``). Unlike the tracker default, that is not a
backward-compatibility choice but the correct one: an unpinned user has
no IDE server, and seeding its rules anyway is the inert-allow failure
GH-768 fixed for trackers.
"""

from __future__ import annotations

import logging

from dev10x.domain.common.ide_choice import Ide, parse_ide
from dev10x.domain.documents.friction_yaml import FrictionYamlDocument

log = logging.getLogger(__name__)


def resolve_ide(*, toplevel: str | None) -> Ide:
    """The IDE configured for ``toplevel``, else the default."""
    if not toplevel:
        return Ide.default()
    document = FrictionYamlDocument(toplevel=toplevel)
    matched = document.matched() or {}
    ide = parse_ide(matched.get("ide"))
    if ide is not None:
        return ide
    ide = parse_ide(document.defaults().get("ide"))
    if ide is not None:
        return ide
    return Ide.default()


def ide_source(*, toplevel: str | None) -> str:
    """Where the resolved IDE came from — for the seeding report."""
    if not toplevel:
        return "default"
    document = FrictionYamlDocument(toplevel=toplevel)
    if parse_ide((document.matched() or {}).get("ide")) is not None:
        return "project"
    if parse_ide(document.defaults().get("ide")) is not None:
        return "defaults"
    return "default"


__all__ = ["ide_source", "resolve_ide"]
