"""Move rules for extracted skills into their satellite's directory (GH-1793).

An ADR-0034 Stage B step moves a skill's scripts out of core's plugin
directory, so a rule a user already holds for one of them stops
matching. This rewrites both spellings Claude Code stores:

- ``plugins/cache/<publisher>/dev10x/<ver>/skills/<skill>/`` →
  ``plugins/cache/<publisher>/<satellite>/<ver>/skills/<skill>/``
- ``plugins/marketplaces/<marketplace>/skills/<skill>/`` →
  ``plugins/marketplaces/<marketplace>/plugins/<key>/skills/<skill>/``

The moved skills come from ``plugins.yaml`` ``extracted:``, so the next
extraction is covered without touching this module. A rewrite cannot
see what is installed, so the cache version segment is kept as is;
``ensure-scripts`` seeds the satellite's own newest version (GH-1886).

An ``allow`` rule is replaced. A ``deny`` or ``ask`` rule is kept and the
relocated copy added next to it: losing a restriction costs more than
carrying one that matches nothing.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.core.paths import satellite_subdir
from dev10x.core.plugin_map import PluginMap, load_plugin_map
from dev10x.domain.common.plugin_version import SEMVER_PATTERN
from dev10x.domain.plugin_identity import CORE_PLUGIN_NAMES
from dev10x.skills.permission.backup import backed_up_write

KEPT_LISTS = ("ask", "deny")
RULE_LISTS = ("allow", *KEPT_LISTS)

CACHE_SKILL_PATTERN = re.compile(
    rf"(plugins/cache/[^/]+/){CORE_PLUGIN_NAMES}(/{SEMVER_PATTERN}/skills/)([^/)]+)/"
)


@dataclass(frozen=True)
class RuleMove:
    rule_list: str
    old: str
    new: str
    kept: bool

    def describe(self) -> str:
        kept = " (original kept)" if self.kept else ""
        return f"  [{self.rule_list}] {self.old} → {self.new}{kept}"


class SatelliteRelocator:
    def __init__(self, *, plugin_map: PluginMap) -> None:
        self._moved = {
            skill: key for key in plugin_map.extracted for skill in plugin_map.plugins.get(key, ())
        }
        self._plugin_names = {
            key: plugin_map.installed_name(key=key) for key in set(self._moved.values())
        }
        self._marketplace_pattern = re.compile(
            rf"(plugins/marketplaces/{re.escape(plugin_map.marketplace)}/)skills/([^/)]+)/"
        )

    @property
    def moved_skills(self) -> dict[str, str]:
        return dict(self._moved)

    def relocate(self, *, rule: str) -> str:
        if "plugins/" not in rule:
            return rule
        rule = CACHE_SKILL_PATTERN.sub(self._cache, rule)
        return self._marketplace_pattern.sub(self._marketplace, rule)

    def _cache(self, match: re.Match[str]) -> str:
        key = self._moved.get(match.group(3))
        if key is None:
            return match.group(0)
        plugin = self._plugin_names[key]
        return f"{match.group(1)}{plugin}{match.group(2)}{match.group(3)}/"

    def _marketplace(self, match: re.Match[str]) -> str:
        key = self._moved.get(match.group(2))
        if key is None:
            return match.group(0)
        return f"{match.group(1)}{satellite_subdir(key=key)}/skills/{match.group(2)}/"

    def relocate_list(
        self,
        *,
        rule_list: str,
        rules: Sequence[Any],
    ) -> tuple[list[Any], list[RuleMove]]:
        keep_original = rule_list in KEPT_LISTS
        taken = {rule for rule in rules if isinstance(rule, str)}
        rewritten: list[Any] = []
        moves: list[RuleMove] = []
        for rule in rules:
            new = self.relocate(rule=rule) if isinstance(rule, str) else rule
            if new == rule:
                rewritten.append(rule)
                continue
            if keep_original:
                rewritten.append(rule)
                if new in taken:
                    continue
            moves.append(RuleMove(rule_list=rule_list, old=rule, new=new, kept=keep_original))
            if new not in taken:
                taken.add(new)
                rewritten.append(new)
        return rewritten, moves

    def relocate_permissions(
        self,
        *,
        permissions: Mapping[str, Any],
    ) -> tuple[dict[str, list[Any]], list[RuleMove]]:
        """A second run finds nothing to change: a replaced rule is gone,
        and a kept rule's relocated copy is already present."""
        lists: dict[str, list[Any]] = {}
        moves: list[RuleMove] = []
        for rule_list in RULE_LISTS:
            rules = permissions.get(rule_list)
            if not isinstance(rules, list):
                continue
            lists[rule_list], list_moves = self.relocate_list(rule_list=rule_list, rules=rules)
            moves.extend(list_moves)
        return lists, moves


def default_relocator() -> SatelliteRelocator:
    return SatelliteRelocator(plugin_map=load_plugin_map())


def relocate_rule(*, rule: str, plugin_map: PluginMap) -> str:
    return SatelliteRelocator(plugin_map=plugin_map).relocate(rule=rule)


def relocate_file(
    path: Path,
    *,
    relocator: SatelliteRelocator | None = None,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """A file that cannot be read or has an unexpected shape returns a
    zero count with one ``SKIP`` line for the caller to show."""
    relocator = relocator or default_relocator()
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        return 0, [f"  SKIP (unreadable): {exc}"]
    except json.JSONDecodeError as exc:
        return 0, [f"  SKIP (invalid JSON): {exc}"]

    permissions = data.get("permissions", {}) if isinstance(data, Mapping) else None
    if not isinstance(permissions, Mapping):
        return 0, ["  SKIP (unexpected structure): no permissions object"]
    _, moves = relocator.relocate_permissions(permissions=permissions)
    if not moves:
        return 0, []

    with backed_up_write(path=path, dry_run=dry_run) as live_data:
        if live_data is not None:
            live_permissions = live_data.setdefault("permissions", {})
            lists, moves = relocator.relocate_permissions(permissions=live_permissions)
            live_permissions.update(lists)

    return len(moves), [move.describe() for move in moves]


__all__ = [
    "CACHE_SKILL_PATTERN",
    "KEPT_LISTS",
    "RULE_LISTS",
    "RuleMove",
    "SatelliteRelocator",
    "default_relocator",
    "relocate_file",
    "relocate_rule",
]
