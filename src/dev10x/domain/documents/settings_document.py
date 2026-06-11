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

from dev10x.domain.file_locks import atomic_write_text, file_lock


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


@dataclass(frozen=True)
class SettingsDocument:
    """A Claude Code ``settings.json`` / ``settings.local.json`` file."""

    path: Path

    def apply_replacements(self, *, replacements: list[tuple[str, str]]) -> int:
        """Rewrite stale prefixes in the ``permissions`` allow/deny lists.

        Performs the full locked read-modify-write so a concurrent
        session never observes a half-written file. Returns the count of
        rules rewritten; writes only when something changed. Raises
        ``json.JSONDecodeError`` / ``OSError`` on read/parse/write failure
        so the caller can decide whether to skip the file.
        """
        with file_lock(self.path):
            new_content, migrated = self.preview_replacements(replacements=replacements)
            if new_content is not None:
                atomic_write_text(self.path, new_content)
        return migrated

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

        This reads ``self.path`` WITHOUT holding ``file_lock``. The
        two-pass migration in ``MigratePluginPermissionsRule`` tolerates
        the read/write gap deliberately (the apply pass re-locks per
        file). A caller that needs the preview to stay consistent with
        the subsequent write MUST hold ``file_lock(self.path)`` across
        both calls itself — ``apply_replacements`` is the locked
        single-file path for that case.
        """
        settings = json.loads(self.path.read_text())
        permissions = settings.get("permissions", {})
        migrated = 0
        changed = False
        for key in ("allow", "deny"):
            raw = permissions.get(key, [])
            if not raw:
                continue
            new_rules, count = _migrate_rules(rules=raw, replacements=replacements)
            new_rules = _deduplicate_rules(rules=new_rules)
            migrated += count
            if count:
                permissions[key] = new_rules
                changed = True
        if not changed:
            return None, migrated
        return json.dumps(settings, indent=2) + "\n", migrated

    def write_migrated(self, content: str) -> None:
        """Atomically write precomputed migrated ``content`` under lock.

        The apply pass of a two-pass migration: the content was already
        computed and validated by :meth:`preview_replacements`, so the
        only remaining failure mode is a write-time I/O error.
        """
        with file_lock(self.path):
            atomic_write_text(self.path, content)


__all__ = ["SettingsDocument", "_migrate_rules", "_deduplicate_rules"]
