"""SettingsDocument — owns settings.json read / transform / atomic write.

Extracted from ``MigratePluginPermissionsRule`` (audit memo D3,
ADR-0007): a Policy Rule must not perform I/O. The rule keeps the
decision (which replacements to apply, which files exist); this Document
owns the locked read-modify-write of the ``permissions`` allow/deny
lists, mirroring the rest of ``domain/documents/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.file_locks import locked_json_update


def _migrate_rules(
    *,
    rules: list[str],
    replacements: list[tuple[str, str]],
) -> tuple[list[str], int]:
    migrated = 0
    result = []
    for rule in rules:
        new_rule = rule
        for old, new in replacements:
            if old in rule:
                new_rule = rule.replace(old, new)
                migrated += 1
                break
        result.append(new_rule)
    return result, migrated


def _deduplicate_rules(rules: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for rule in rules:
        if rule not in seen:
            seen.add(rule)
            deduped.append(rule)
    return deduped


def _migrate_permissions(
    permissions: dict[str, list[str]],
    *,
    replacements: list[tuple[str, str]],
) -> int:
    """Rewrite stale prefixes in the allow/deny lists in place.

    Mutates ``permissions`` and returns the count of rules rewritten. A
    key is only reassigned (and deduplicated) when at least one of its
    rules changed, so an untouched list keeps its original ordering.
    """
    migrated = 0
    for key in ("allow", "deny"):
        raw = permissions.get(key, [])
        if not raw:
            continue
        new_rules, count = _migrate_rules(rules=raw, replacements=replacements)
        if count:
            permissions[key] = _deduplicate_rules(rules=new_rules)
            migrated += count
    return migrated


@dataclass(frozen=True)
class SettingsDocument:
    """A Claude Code ``settings.json`` / ``settings.local.json`` file."""

    path: Path

    def apply_replacements(self, *, replacements: list[tuple[str, str]]) -> int:
        """Rewrite stale prefixes in the ``permissions`` allow/deny lists.

        Runs the read-modify-write under :func:`locked_json_update` — the
        SAME lock (and ``settings.local.lock`` sidecar) the permission
        skills use for this file — so the migration mutually excludes with
        a concurrent ``doctor`` / ``update_paths`` run, not merely with
        another migration. ``file_lock`` would append ``.lock`` to the
        full name (``settings.local.json.lock``), a different sidecar that
        does NOT exclude those callers (GH-825, GH-827 review). Re-reads a
        fresh copy under the lock so an edit landing after the dry-run
        preview is re-migrated, not clobbered. Returns the count of rules
        rewritten. Raises ``json.JSONDecodeError`` / ``OSError`` on
        read/parse/write failure so the caller can decide whether to skip.
        """
        with locked_json_update(self.path) as settings:
            permissions = settings.get("permissions")
            if not isinstance(permissions, dict):
                return 0
            return _migrate_permissions(permissions, replacements=replacements)

    def preview_replacements(
        self, *, replacements: list[tuple[str, str]]
    ) -> tuple[str | None, int]:
        """Compute the migrated file content without writing it.

        Returns ``(new_content, count)`` where ``new_content`` is the
        serialised JSON to write, or ``None`` when nothing changed.
        Raises ``json.JSONDecodeError`` / ``OSError`` on read/parse
        failure so a multi-file caller can validate every file *before*
        writing any of them (the dry-run pass of a two-pass migration,
        ADR-0011 Layer 4).

        This reads ``self.path`` WITHOUT holding a lock — it is a
        read-only dry run. It never commits its result: the apply pass in
        ``MigratePluginPermissionsRule`` calls :meth:`apply_replacements`,
        which re-reads and re-migrates under the lock, so an edit landing
        after this preview is not clobbered (GH-825). Any caller that
        needs a preview-then-write MUST likewise go through
        :meth:`apply_replacements` — never persist this method's output
        directly.
        """
        settings = json.loads(self.path.read_text())
        permissions = settings.get("permissions")
        if not isinstance(permissions, dict):
            return None, 0
        migrated = _migrate_permissions(permissions, replacements=replacements)
        if not migrated:
            return None, migrated
        return json.dumps(settings, indent=2) + "\n", migrated


__all__ = ["SettingsDocument", "_migrate_rules", "_deduplicate_rules"]
