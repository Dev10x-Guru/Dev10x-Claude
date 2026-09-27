"""Carry permission rules across the ``Dev10x`` -> ``dev10x`` rename (GH-1501).

GH-1499 renamed the plugin so marketplace sync accepts it. Rules a user
wrote against the old name — ``Skill(Dev10x:*)``, ``mcp__plugin_Dev10x_*``
and the ``Dev10x@Dev10x-Guru`` ``enabledPlugins`` id — match nothing
afterwards. For an allow rule that is a new prompt; for a deny or ask rule
it is a guardrail that silently stopped guarding.

So every legacy rule is rewritten in place, never dropped. The one
exception is a rule whose new spelling is already in the same list: the
legacy copy is then pruned, because the protection or grant it carried is
already present. That is also what makes a second pass a no-op.

Only the permission namespace moved. The ``Dev10x`` config directories
and the ``~/.claude/skills/Dev10x:upgrade-cleanup/`` path kept their names
on purpose, so matching is anchored to the start of a rule: a
``Read(~/.claude/skills/Dev10x:upgrade-cleanup/**)`` is left alone.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal

RuleList = Literal["deny", "ask", "allow"]

RULE_LISTS: tuple[RuleList, ...] = ("deny", "ask", "allow")

LEGACY_RULE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("Skill(Dev10x:", "Skill(dev10x:"),
    ("mcp__plugin_Dev10x_", "mcp__plugin_dev10x_"),
)

LEGACY_PLUGIN_ID = "Dev10x@Dev10x-Guru"
CURRENT_PLUGIN_ID = "dev10x@Dev10x-Guru"


def current_spelling(rule: str) -> str | None:
    """The post-rename spelling of ``rule``, or ``None`` when it has none."""
    for legacy, current in LEGACY_RULE_PREFIXES:
        if rule.startswith(legacy):
            return current + rule[len(legacy) :]
    return None


@dataclass(frozen=True)
class RuleMove:
    """One legacy rule and what became of it."""

    list_name: RuleList
    legacy: str
    current: str
    pruned: bool

    def describe(self) -> str:
        if self.pruned:
            return f"{self.list_name}: pruned {self.legacy} ({self.current} already present)"
        return f"{self.list_name}: {self.legacy} -> {self.current}"


@dataclass(frozen=True)
class PluginIdMove:
    """The legacy ``enabledPlugins`` key and what became of it."""

    pruned: bool

    def describe(self) -> str:
        if self.pruned:
            return (
                f"enabledPlugins: pruned {LEGACY_PLUGIN_ID} ({CURRENT_PLUGIN_ID} already present)"
            )
        return f"enabledPlugins: {LEGACY_PLUGIN_ID} -> {CURRENT_PLUGIN_ID}"


@dataclass(frozen=True)
class NamespaceMigration:
    """Every legacy spelling found in one settings document."""

    rule_moves: tuple[RuleMove, ...] = ()
    plugin_id_move: PluginIdMove | None = None

    @property
    def count(self) -> int:
        return len(self.rule_moves) + (0 if self.plugin_id_move is None else 1)

    @property
    def changed(self) -> bool:
        return self.count > 0

    def describe(self) -> list[str]:
        lines = [move.describe() for move in self.rule_moves]
        if self.plugin_id_move is not None:
            lines.append(self.plugin_id_move.describe())
        return lines


def _migrate_rules(
    *,
    list_name: RuleList,
    rules: list[Any],
) -> tuple[list[Any], list[RuleMove]]:
    present = {rule for rule in rules if isinstance(rule, str)}
    migrated: list[Any] = []
    moves: list[RuleMove] = []
    for rule in rules:
        current = current_spelling(rule) if isinstance(rule, str) else None
        if current is None:
            migrated.append(rule)
            continue
        pruned = current in present
        moves.append(RuleMove(list_name=list_name, legacy=rule, current=current, pruned=pruned))
        if not pruned:
            migrated.append(current)
            present.add(current)
    return migrated, moves


def _migrate_plugin_ids(*, plugins: dict[str, Any]) -> tuple[dict[str, Any], PluginIdMove]:
    pruned = CURRENT_PLUGIN_ID in plugins
    migrated = {
        (CURRENT_PLUGIN_ID if key == LEGACY_PLUGIN_ID else key): value
        for key, value in plugins.items()
        if not (pruned and key == LEGACY_PLUGIN_ID)
    }
    return migrated, PluginIdMove(pruned=pruned)


def migrate_legacy_namespace(data: dict[str, Any]) -> tuple[dict[str, Any], NamespaceMigration]:
    """Return ``data`` with legacy spellings migrated, and what moved.

    ``data`` is not mutated, so a dry run and a write share one code path.
    """
    migrated = copy.deepcopy(data)
    rule_moves: list[RuleMove] = []
    permissions = migrated.get("permissions")
    if isinstance(permissions, dict):
        for list_name in RULE_LISTS:
            rules = permissions.get(list_name)
            if not isinstance(rules, list):
                continue
            new_rules, moves = _migrate_rules(list_name=list_name, rules=rules)
            permissions[list_name] = new_rules
            rule_moves.extend(moves)

    plugin_id_move: PluginIdMove | None = None
    plugins = migrated.get("enabledPlugins")
    if isinstance(plugins, dict) and LEGACY_PLUGIN_ID in plugins:
        migrated["enabledPlugins"], plugin_id_move = _migrate_plugin_ids(plugins=plugins)

    return migrated, NamespaceMigration(
        rule_moves=tuple(rule_moves),
        plugin_id_move=plugin_id_move,
    )


__all__ = [
    "CURRENT_PLUGIN_ID",
    "LEGACY_PLUGIN_ID",
    "NamespaceMigration",
    "PluginIdMove",
    "RuleMove",
    "current_spelling",
    "migrate_legacy_namespace",
]
