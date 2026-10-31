"""Plan per-project skill pruning in Claude Code settings (GH-1627).

Claude Code hides a skill per project through ``skillOverrides``
(``{"<skill>": "off" | "name-only" | "user-invocable-only" | "on"}``),
but that key does **not** reach plugin skills — those are switched off a
whole plugin at a time through ``enabledPlugins: {"<plugin>@<market>":
false}``. A proposal naming a plugin skill (``impeccable:audit``) in
``skillOverrides`` would be written and silently ignored, so this module
refuses it and points at the plugin instead.

The planner is pure: it takes the current settings dict and returns what
would change, so the skill can show a concrete diff before anything is
written, and re-running it on already-pruned settings yields no changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from dev10x.core.domain.common.result import Result, err, ok

SKILL_OVERRIDES_KEY = "skillOverrides"
ENABLED_PLUGINS_KEY = "enabledPlugins"


class Visibility(StrEnum):
    ON = "on"
    NAME_ONLY = "name-only"
    USER_INVOCABLE_ONLY = "user-invocable-only"
    OFF = "off"


@dataclass(frozen=True)
class OverrideChange:
    name: str
    before: str | None
    after: str


@dataclass(frozen=True)
class PrunePlan:
    skill_changes: tuple[OverrideChange, ...] = ()
    plugin_disables: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    kept_by_allowlist: tuple[str, ...] = ()
    plugin_skills_refused: tuple[str, ...] = ()
    existing_overrides: dict[str, str] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(self.skill_changes or self.plugin_disables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_changes": self.has_changes,
            "skill_changes": [
                {"name": c.name, "before": c.before, "after": c.after} for c in self.skill_changes
            ],
            "plugin_disables": list(self.plugin_disables),
            "unchanged": list(self.unchanged),
            "kept_by_allowlist": list(self.kept_by_allowlist),
            "plugin_skills_refused": list(self.plugin_skills_refused),
            "existing_overrides": dict(self.existing_overrides),
        }


def parse_allowlist(*, text: str, source: str) -> Result[frozenset[str]]:
    """Read the ``keep:`` list of a skill-prune allowlist.

    A malformed allowlist is an error, never an empty one: treating it as
    empty would let ``--apply`` hide exactly the skills the user asked to
    keep.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return err(f"cannot parse allowlist {source}: {exc}")
    if data is None:
        return ok(frozenset())
    keep = data.get("keep") if isinstance(data, dict) else data
    if keep is None:
        return ok(frozenset())
    if not isinstance(keep, list) or not all(isinstance(name, str) for name in keep):
        return err(f"allowlist {source}: 'keep' must be a list of skill names")
    return ok(frozenset(keep))


def load_allowlist(*, path: Path, required: bool) -> Result[frozenset[str]]:
    """Load ``path``; a missing file is empty unless the caller named it."""
    if not path.is_file():
        if required:
            return err(f"allowlist not found: {path}")
        return ok(frozenset())
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return err(f"cannot read allowlist {path}: {exc}")
    return parse_allowlist(text=text, source=str(path))


def parse_settings(*, text: str, source: str) -> Result[dict[str, Any]]:
    """Parse a Claude Code settings file, which must hold a JSON object."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return err(f"cannot read {source}: {exc}")
    if not isinstance(data, dict):
        return err(f"{source} must hold a JSON object, got {type(data).__name__}")
    return ok(data)


def is_plugin_skill(*, name: str) -> bool:
    return ":" in name


def _current_overrides(*, settings: dict[str, Any]) -> dict[str, str]:
    raw = settings.get(SKILL_OVERRIDES_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _plugin_already_disabled(*, settings: dict[str, Any], plugin_id: str) -> bool:
    plugins = settings.get(ENABLED_PLUGINS_KEY)
    return isinstance(plugins, dict) and plugins.get(plugin_id) is False


def plan_prune(
    *,
    settings: dict[str, Any],
    proposed: dict[str, Visibility],
    plugin_disables: tuple[str, ...] = (),
    allowlist: frozenset[str] = frozenset(),
) -> PrunePlan:
    """Compare ``proposed`` visibilities against ``settings``.

    A name on ``allowlist`` is never changed — the user's standing "keep
    this" outranks a fresh proposal. A plugin in ``plugin_disables`` is
    kept when any allowlisted skill belongs to it.
    """
    current = _current_overrides(settings=settings)
    changes: list[OverrideChange] = []
    unchanged: list[str] = []
    kept: list[str] = []
    refused: list[str] = []
    for name in sorted(proposed):
        visibility = proposed[name]
        if name in allowlist:
            kept.append(name)
        elif is_plugin_skill(name=name):
            refused.append(name)
        elif current.get(name) == visibility.value:
            unchanged.append(name)
        else:
            changes.append(
                OverrideChange(name=name, before=current.get(name), after=visibility.value)
            )
    disables: list[str] = []
    for plugin_id in sorted(set(plugin_disables)):
        plugin_name = plugin_id.split("@", 1)[0]
        if any(keep.split(":", 1)[0] == plugin_name for keep in allowlist if ":" in keep):
            kept.append(plugin_id)
        elif _plugin_already_disabled(settings=settings, plugin_id=plugin_id):
            unchanged.append(plugin_id)
        else:
            disables.append(plugin_id)
    return PrunePlan(
        skill_changes=tuple(changes),
        plugin_disables=tuple(disables),
        unchanged=tuple(unchanged),
        kept_by_allowlist=tuple(kept),
        plugin_skills_refused=tuple(refused),
        existing_overrides=current,
    )


def apply_prune(*, settings: dict[str, Any], plan: PrunePlan) -> dict[str, Any]:
    """Return ``settings`` with ``plan`` merged in; the input is not mutated.

    Existing ``skillOverrides`` and ``enabledPlugins`` entries the plan
    does not name are preserved untouched.
    """
    merged = dict(settings)
    if plan.skill_changes:
        overrides = _current_overrides(settings=settings)
        overrides.update({change.name: change.after for change in plan.skill_changes})
        merged[SKILL_OVERRIDES_KEY] = dict(sorted(overrides.items()))
    if plan.plugin_disables:
        plugins = settings.get(ENABLED_PLUGINS_KEY)
        enabled = dict(plugins) if isinstance(plugins, dict) else {}
        enabled.update({plugin_id: False for plugin_id in plan.plugin_disables})
        merged[ENABLED_PLUGINS_KEY] = enabled
    return merged


__all__ = [
    "ENABLED_PLUGINS_KEY",
    "SKILL_OVERRIDES_KEY",
    "OverrideChange",
    "PrunePlan",
    "Visibility",
    "apply_prune",
    "is_plugin_skill",
    "load_allowlist",
    "parse_allowlist",
    "parse_settings",
    "plan_prune",
]
