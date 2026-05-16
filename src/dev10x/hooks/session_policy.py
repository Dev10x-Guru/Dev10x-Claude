"""Session policy — named Rule objects for friction parsing, permission
migration, and decision-guidance synthesis.

Rule archetype: each class encapsulates one named decision the session
hooks make. Pulling these out of ``hooks/session.py`` keeps the
dispatcher thin and makes the policies testable in isolation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.session_state import PlanSummary


class UnknownFrictionLevelError(ValueError):
    """Raised when decision guidance is asked to format an unknown friction level."""


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
class ReadFrictionLevelRule:
    """Read the friction level from ``.claude/Dev10x/session.yaml``.

    Returns ``FrictionLevel.default()`` when the file is missing or
    unreadable — that is the soft fallback. Use ``DecisionGuidanceRule``
    for strict behaviour at format time.
    """

    toplevel: str

    def apply(self) -> FrictionLevel:
        session_yaml = Path(self.toplevel) / ".claude" / "Dev10x" / "session.yaml"
        if not session_yaml.exists():
            return FrictionLevel.default()
        try:
            import yaml

            with open(session_yaml) as f:
                data = yaml.safe_load(f) or {}
            return FrictionLevel.from_yaml(data.get("friction_level"))
        except Exception:
            return FrictionLevel.default()


@dataclass(frozen=True)
class DecisionGuidanceRule:
    """Format resume guidance for the agent based on plan + friction level.

    Raises ``UnknownFrictionLevelError`` when ``friction_level`` is not
    a recognised :class:`FrictionLevel` member. Audit M7 #D2 calls out
    the prior fall-through (which silently produced strict-style guidance
    for adaptive sessions) as a latent bug.
    """

    plan: dict[str, Any]
    friction_level: FrictionLevel

    def apply(self) -> str:
        if not isinstance(self.friction_level, FrictionLevel):
            raise UnknownFrictionLevelError(f"Unknown friction level: {self.friction_level!r}")

        summary = PlanSummary.from_dict(data=self.plan)
        decisions = summary.pending_decisions
        if not decisions:
            has_remaining = any(
                t.get("status") not in ("completed", "deleted") for t in summary.tasks
            )
            if has_remaining:
                return "Session resumed with tasks remaining. Auto-advance through the task list."
            return ""

        if self.friction_level is FrictionLevel.ADAPTIVE:
            return (
                "Session resumed with pending decisions. Friction level is adaptive — "
                "auto-select recommended options for all queued decisions and continue "
                "advancing through the task list without calling AskUserQuestion."
            )
        if self.friction_level in (FrictionLevel.STRICT, FrictionLevel.GUIDED):
            return (
                "Session resumed with pending decisions. "
                "Re-ask each pending decision using AskUserQuestion — "
                "invoke Dev10x:ask before advancing."
            )
        raise UnknownFrictionLevelError(f"Unhandled friction level: {self.friction_level!r}")


@dataclass(frozen=True)
class MigratePluginPermissionsRule:
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

        total_migrated = 0
        files_changed: list[str] = []

        for settings_file in settings_files:
            try:
                with file_lock(settings_file):
                    settings = json.loads(settings_file.read_text())
                    permissions = settings.get("permissions", {})
                    changed = False
                    for key in ("allow", "deny"):
                        raw = permissions.get(key, [])
                        if not raw:
                            continue
                        new_rules, count = _migrate_rules(rules=raw, replacements=replacements)
                        new_rules = _deduplicate_rules(rules=new_rules)
                        total_migrated += count
                        if count:
                            permissions[key] = new_rules
                            changed = True
                    if not changed:
                        continue
                    atomic_write_text(settings_file, json.dumps(settings, indent=2) + "\n")
                files_changed.append(settings_file.name)
            except (json.JSONDecodeError, OSError):
                continue

        return total_migrated, files_changed


__all__ = [
    "UnknownFrictionLevelError",
    "ReadFrictionLevelRule",
    "DecisionGuidanceRule",
    "MigratePluginPermissionsRule",
    "_build_migration_replacements",
    "_migrate_rules",
    "_deduplicate_rules",
]
