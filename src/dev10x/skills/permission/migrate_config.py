"""Migrate legacy per-repo durable prefs into the global friction.yaml (GH-812 R4).

ADR-0018 retired the per-repo ``.claude/Dev10x/{session,config}.yaml`` in
favor of the global ``~/.config/Dev10x/friction.yaml`` (keyed by project
dir-path globs). PR #815 shipped only a lazy *read* fallback, so existing
repos keep working but their prefs never migrate and the stale files linger.

This module is the agent-driven upgrade-cleanup step that completes the
migration:

1. **Detect** a legacy ``config.yaml`` (and any pre-split ``session.yaml``
   durable keys) in a scanned repo.
2. **Fold** its durable keys into a ``projects[]`` entry in the global
   ``friction.yaml`` (match glob for that repo).
3. **Remove** the stale per-repo files once friction.yaml parity is confirmed.

Runtime resolvers only *read* friction.yaml (keeping Claude Code's
self-settings gate quiet); this migration is the sanctioned writer.

CLI entry point: ``dev10x permission doctor migrate-config``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.documents.session_yaml import (
    DURABLE_KEYS,
    ConfigYamlDocument,
    FrictionYamlDocument,
    SessionYamlDocument,
    legacy_durable_prefs,
)


def _load_session_mapping(*, root: Path) -> dict[str, Any]:
    """Load the pre-split ``session.yaml`` mapping (durable-key detection)."""
    path = SessionYamlDocument(toplevel=str(root)).path
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _stale_files(*, root: Path, has_durable_session: bool) -> list[Path]:
    """Return the legacy files this migration removes.

    ``config.yaml`` is fully retired (ADR-0018) — removed whenever present.
    A ``session.yaml`` is removed only when it carries durable keys (a
    pre-split legacy file); an ephemeral session.yaml (branch/tickets only)
    is left untouched.
    """
    config_path = ConfigYamlDocument(toplevel=str(root)).path
    session_path = SessionYamlDocument(toplevel=str(root)).path
    stale: list[Path] = []
    if config_path.exists():
        stale.append(config_path)
    if has_durable_session and session_path.exists():
        stale.append(session_path)
    return stale


def detect_legacy_config(*, root: Path) -> dict[str, Any] | None:
    """Detect a legacy per-repo durable config under ``root``.

    Returns ``None`` when there is nothing to migrate — no ``config.yaml``
    and no pre-split ``session.yaml`` carrying durable keys. Otherwise
    returns the finding: the folded durable prefs and the stale files.
    """
    config_path = ConfigYamlDocument(toplevel=str(root)).path
    session_durable = {
        key: value
        for key, value in _load_session_mapping(root=root).items()
        if key in DURABLE_KEYS
    }
    if not config_path.exists() and not session_durable:
        return None
    return {
        "durable_prefs": legacy_durable_prefs(toplevel=str(root)),
        "stale_files": [
            str(path)
            for path in _stale_files(root=root, has_durable_session=bool(session_durable))
        ],
    }


def _parity(*, matched: dict[str, Any] | None, prefs: dict[str, Any]) -> bool:
    """Confirm every migrated durable pref reads back from friction.yaml."""
    if matched is None:
        return False
    return all(matched.get(key) == value for key, value in prefs.items())


def migrate_config_to_friction(*, root: Path, dry_run: bool = False) -> dict[str, Any]:
    """Fold a repo's legacy durable prefs into friction.yaml, remove stale files.

    Idempotent: the ``projects[]`` entry is keyed by the repo's match globs,
    so a re-run replaces (not duplicates) it. On ``dry_run`` nothing is
    written — the planned entry and rendered file are returned for preview.
    The stale files are removed only after friction.yaml parity is confirmed.
    """
    finding = detect_legacy_config(root=root)
    if finding is None:
        return {"migrated": False, "reason": "no legacy config found", "removed": []}

    prefs: dict[str, Any] = finding["durable_prefs"]
    match = FrictionYamlDocument.match_globs_for(str(root))
    friction = FrictionYamlDocument(toplevel=str(root))
    new_doc = FrictionYamlDocument.with_project(friction._doc(), match=match, prefs=prefs)
    content = FrictionYamlDocument.render_document(new_doc)

    if dry_run:
        return {
            "migrated": False,
            "dry_run": True,
            "match": match,
            "prefs": prefs,
            "friction_yaml": str(friction.path),
            "stale_files": finding["stale_files"],
            "content": content,
        }

    friction.path.parent.mkdir(parents=True, exist_ok=True)
    friction.path.write_text(content)

    matched = FrictionYamlDocument(toplevel=str(root)).matched()
    if not _parity(matched=matched, prefs=prefs):
        return {
            "error": "friction.yaml parity check failed after write; stale files left in place",
            "friction_yaml": str(friction.path),
        }

    removed: list[str] = []
    for path_str in finding["stale_files"]:
        Path(path_str).unlink(missing_ok=True)
        removed.append(path_str)

    return {
        "migrated": True,
        "match": match,
        "prefs": prefs,
        "friction_yaml": str(friction.path),
        "removed": removed,
    }
