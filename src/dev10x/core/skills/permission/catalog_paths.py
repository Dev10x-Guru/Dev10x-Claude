"""Locate the shipped upgrade-cleanup catalog from any install layout (GH-1190).

Four modules used to compute this path themselves as
``Path(__file__).resolve().parents[4] / "skills" / "upgrade-cleanup" /
"projects.yaml"``. From a checkout that hop lands on the repo root and is
correct. From an installed wheel it is not: ``dev10x/`` sits in
``site-packages`` and ``skills/`` is not package data beside it, so the
path names a file that cannot exist.

Nothing raised. Readers that degrade gracefully on an unreadable catalog
— :func:`dev10x.skills.permission.doctor.catalogued_rules` by design —
then produced the failure shape the permission-friction work keeps
fighting: "we could not check" is indistinguishable from "nothing is
wrong", so the GH-1151 cross-contamination exemption silently stopped
applying and ``doctor`` resumed flagging rules ``ensure-base`` had just
written.

:func:`dev10x.domain.plugin_root.resolve_plugin_root` already answers
"where is the plugin" for both layouts. This module is the single place
that turns that answer into the catalog path, so the four call sites
cannot drift apart again.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.plugin_root import resolve_plugin_root

CATALOG_RELPATH = Path("skills") / "upgrade-cleanup" / "projects.yaml"


def shipped_projects_catalog(*, plugin_root: Path | None = None) -> Path | None:
    """Return the shipped ``projects.yaml`` path, or ``None`` when unresolvable.

    ``None`` means no plugin root exists on this machine — a genuinely
    absent catalog, which callers MUST report as such rather than
    folding into "the catalog declared nothing".

    Args:
        plugin_root: Plugin root to resolve against. Defaults to the
            root :func:`resolve_plugin_root` finds.
    """
    root = plugin_root if plugin_root is not None else resolve_plugin_root()
    if root is None:
        return None
    return root / CATALOG_RELPATH


__all__ = ["CATALOG_RELPATH", "shipped_projects_catalog"]
