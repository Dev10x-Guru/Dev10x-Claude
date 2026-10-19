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

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from dev10x.core.config.fragments import (
    ConfigFragment,
    discover_fragments,
    load_merged,
    plugin_order,
)
from dev10x.domain.plugin_root import resolve_plugin_root

CATALOG_RELPATH = Path("skills") / "upgrade-cleanup" / "projects.yaml"
FRAGMENTS_DIRNAME = "projects.d"


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


def catalog_fragment_dirs(*, catalog_path: Path) -> tuple[Path, ...]:
    return (catalog_path.parent / FRAGMENTS_DIRNAME,)


def catalog_fragments(
    *,
    catalog_path: Path,
    fragment_dirs: Sequence[Path] | None = None,
) -> list[ConfigFragment]:
    candidates = (
        catalog_fragment_dirs(catalog_path=catalog_path)
        if fragment_dirs is None
        else fragment_dirs
    )
    directories = [directory for directory in candidates if directory.is_dir()]
    if not directories:
        return []
    return discover_fragments(directories=directories, plugins=plugin_order())


def catalog_files(
    *,
    catalog_path: Path,
    fragment_dirs: Sequence[Path] | None = None,
) -> list[Path]:
    fragments = catalog_fragments(catalog_path=catalog_path, fragment_dirs=fragment_dirs)
    return [catalog_path, *(fragment.path for fragment in fragments)]


def load_catalog_document(
    *,
    catalog_path: Path,
    fragment_dirs: Sequence[Path] | None = None,
) -> Any:
    base = yaml.safe_load(catalog_path.read_text())
    fragments = catalog_fragments(catalog_path=catalog_path, fragment_dirs=fragment_dirs)
    if not fragments:
        return base
    return load_merged(fragments=fragments, base=(str(catalog_path), base or {}))


def catalog_text(
    *,
    catalog_path: Path,
    fragment_dirs: Sequence[Path] | None = None,
) -> str:
    text = catalog_path.read_text()
    if not catalog_fragments(catalog_path=catalog_path, fragment_dirs=fragment_dirs):
        return text
    # GH-1589: fragments repeat top-level keys such as `base_permissions`.
    # Concatenated, PyYAML keeps only the last occurrence of a duplicate
    # key, so a fresh userspace copy would lose every core rule. Render
    # the merged document instead, under the base file's header.
    document = load_catalog_document(catalog_path=catalog_path, fragment_dirs=fragment_dirs)
    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    return f"{_leading_comment(text=text)}{body}"


def _leading_comment(*, text: str) -> str:
    header: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.strip() and not line.lstrip().startswith("#"):
            break
        header.append(line)
    return "".join(header)


__all__ = [
    "CATALOG_RELPATH",
    "FRAGMENTS_DIRNAME",
    "catalog_files",
    "catalog_fragment_dirs",
    "catalog_fragments",
    "catalog_text",
    "load_catalog_document",
    "shipped_projects_catalog",
]
