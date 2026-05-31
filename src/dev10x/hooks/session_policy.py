"""Session policy — named Rule objects for permission migration and
autonomy-reassurance synthesis.

Rule archetype (see ADR-0007): each class encapsulates one named
decision the session hooks make. Pulling these out of
``hooks/session.py`` keeps the dispatcher thin and makes the policies
testable in isolation.

The friction-parsing and decision-guidance rules moved to
``dev10x.domain.session_rules`` (ADR-0008) because they are pure
domain policies; they are re-exported here for backward compatibility.
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
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.rules.policy_rule import PolicyRule
from dev10x.domain.session_rules import (
    DecisionGuidanceRule,
    ReadFrictionLevelRule,
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
class BuildAutonomyReassuranceRule(PolicyRule[str]):
    """Build a reassurance block for autonomous sessions (GH-261).

    Fires only when ``friction_level: adaptive`` AND ``solo-maintainer`` is in
    ``active_modes``. Reassures the agent that long task lists are by design
    and that re-asking settled scope decisions is the drift mode the
    supervisor explicitly opted out of.

    Returns an empty string outside the autonomous-shipping profile so the
    SessionStart orchestrator can drop the segment silently.
    """

    toplevel: str

    REASSURANCE_TEXT = (
        "**Supervisor monitors context.** Long task lists are by design — "
        "the work-on skill creates one task per play step so the supervisor "
        'sees scope upfront. Do NOT pause to ask "should I proceed?" when:\n'
        "\n"
        "- The user already answered a scope AskUserQuestion\n"
        "- friction_level: adaptive is set (auto-advance is the contract)\n"
        "- The skill instructions explicitly cover the next step\n"
        "\n"
        "If context truly becomes a problem, the supervisor will interrupt. "
        "Context anxiety is the agent's drift mode — trust the plan."
    )

    def apply(self) -> str:
        session_yaml = Path(self.toplevel) / ".claude" / "Dev10x" / "session.yaml"
        if not session_yaml.exists():
            return ""
        try:
            import yaml

            with open(session_yaml) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return ""

        level = FrictionLevel.from_yaml(data.get("friction_level"))
        modes = data.get("active_modes") or []
        if level is not FrictionLevel.ADAPTIVE:
            return ""
        if "solo-maintainer" not in modes:
            return ""
        return self.REASSURANCE_TEXT


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

        total_migrated = 0
        files_changed: list[str] = []

        for settings_file in settings_files:
            try:
                count = SettingsDocument(path=settings_file).apply_replacements(
                    replacements=replacements
                )
            except (json.JSONDecodeError, OSError):
                continue
            if count:
                total_migrated += count
                files_changed.append(settings_file.name)

        return total_migrated, files_changed


__all__ = [
    "UnknownFrictionLevelError",
    "ReadFrictionLevelRule",
    "BuildAutonomyReassuranceRule",
    "DecisionGuidanceRule",
    "MigratePluginPermissionsRule",
    "_build_migration_replacements",
    "_migrate_rules",
    "_deduplicate_rules",
]
