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
            if changed:
                atomic_write_text(self.path, json.dumps(settings, indent=2) + "\n")
        return migrated


__all__ = ["SettingsDocument", "_migrate_rules", "_deduplicate_rules"]
