"""Session policy — named Rule objects for permission migration.

Rule archetype (see ADR-0007): each class encapsulates one named
decision the session hooks make. Pulling these out of
``hooks/session.py`` keeps the dispatcher thin and makes the policies
testable in isolation.

The friction-parsing, decision-guidance, and autonomy-reassurance rules
moved to ``dev10x.domain.session_rules`` (ADR-0008) because they are
pure domain policies; they are re-exported here for backward
compatibility. The session.yaml read those rules used to perform is now
owned by ``dev10x.domain.documents.session_yaml.SessionYamlDocument``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.documents.settings_document import (
    SettingsDocument,
    _deduplicate_rules,
    _migrate_rules,
)
from dev10x.domain.rules.policy_rule import PolicyRule
from dev10x.domain.session_rules import (
    BuildAutonomyReassuranceRule,
    DecisionGuidanceRule,
    UnknownFrictionLevelError,
)


def _build_migration_replacements(
    *,
    plugin_root: Path,
    home: str,
) -> list[tuple[str, str]]:
    version_parent = plugin_root.parent
    current_abs = str(plugin_root) + "/"
    current_tilde = current_abs.replace(home, "~")

    replacements: list[tuple[str, str]] = []
    try:
        children = sorted(version_parent.iterdir())
    except OSError:
        return replacements

    for child in children:
        if not child.is_dir() or child == plugin_root:
            continue
        old_abs = str(child) + "/"
        old_tilde = old_abs.replace(home, "~")
        replacements.append((old_abs, current_abs))
        replacements.append((old_tilde, current_tilde))

    return replacements


@dataclass(frozen=True)
class MigratePluginPermissionsRule(PolicyRule[tuple[int, list[str]]]):
    """Rewrite stale plugin-cache paths in user settings.{json,local.json}.

    Only meaningful when installed via the plugin cache — direct
    ``--plugin-dir`` installs have no version-pinned ancestors to clean
    up. Returns the count of rules rewritten and the list of files
    touched so the dispatcher can emit a single informational line.
    """

    plugin_root: Path
    home_path: Path

    def applicable(self) -> bool:
        return "plugins/cache/" in str(self.plugin_root)

    def apply(self) -> tuple[int, list[str]]:
        replacements = _build_migration_replacements(
            plugin_root=self.plugin_root,
            home=str(self.home_path),
        )
        if not replacements:
            return 0, []

        settings_files = [
            f
            for f in [
                self.home_path / ".claude" / "settings.json",
                self.home_path / ".claude" / "settings.local.json",
            ]
            if f.exists()
        ]

        # Two-pass dry-run-then-apply (ADR-0011 Layer 4): compute and
        # validate every file's migrated content before writing any of
        # them. This keeps all parse/transform failures in the read pass
        # so a corrupt file can no longer leave an already-written sibling
        # mismatched. The only failure left in the write pass is a true
        # I/O error, which we surface instead of swallowing.
        planned: list[tuple[SettingsDocument, str, int]] = []
        for settings_file in settings_files:
            doc = SettingsDocument(path=settings_file)
            try:
                new_content, count = doc.preview_replacements(replacements=replacements)
            except (json.JSONDecodeError, OSError):
                continue
            if count and new_content is not None:
                planned.append((doc, new_content, count))

        total_migrated = 0
        files_changed: list[str] = []
        for doc, new_content, count in planned:
            doc.write_migrated(new_content)
            total_migrated += count
            files_changed.append(doc.path.name)

        return total_migrated, files_changed


__all__ = [
    "UnknownFrictionLevelError",
    "BuildAutonomyReassuranceRule",
    "DecisionGuidanceRule",
    "MigratePluginPermissionsRule",
    "_build_migration_replacements",
    "_migrate_rules",
    "_deduplicate_rules",
]
