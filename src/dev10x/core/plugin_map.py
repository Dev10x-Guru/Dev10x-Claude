"""Skill-to-plugin assignment for the staged plugin split (ADR-0034, GH-1524)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

PLUGIN_MAP_PATH = Path(__file__).with_name("plugins.yaml")


@dataclass(frozen=True)
class PluginMap:
    plugins: dict[str, tuple[str, ...]]

    @property
    def assignments(self) -> list[tuple[str, str]]:
        return [(skill, plugin) for plugin, skills in self.plugins.items() for skill in skills]

    def plugin_for(self, *, skill: str) -> str | None:
        for assigned_skill, plugin in self.assignments:
            if assigned_skill == skill:
                return plugin
        return None

    def duplicated_skills(self) -> list[str]:
        counts = Counter(skill for skill, _ in self.assignments)
        return sorted(skill for skill, count in counts.items() if count > 1)

    def unassigned_skills(self, *, skill_dirs: Iterable[str]) -> list[str]:
        assigned = {skill for skill, _ in self.assignments}
        return sorted(set(skill_dirs) - assigned)

    def unknown_skills(self, *, skill_dirs: Iterable[str]) -> list[str]:
        known = set(skill_dirs)
        return sorted({skill for skill, _ in self.assignments} - known)

    def counts(self) -> dict[str, int]:
        return {plugin: len(skills) for plugin, skills in self.plugins.items()}


def parse_plugin_map(*, data: dict[str, dict[str, list[str]]]) -> PluginMap:
    plugins = data.get("plugins") or {}
    return PluginMap(
        plugins={plugin: tuple(skills or ()) for plugin, skills in plugins.items()},
    )


def load_plugin_map(*, path: Path = PLUGIN_MAP_PATH) -> PluginMap:
    return parse_plugin_map(data=yaml.safe_load(path.read_text()) or {})


def skill_directories(*, skills_root: Path) -> list[str]:
    return sorted(
        entry.name
        for entry in skills_root.iterdir()
        if entry.is_dir() and (entry / "SKILL.md").is_file()
    )


__all__ = [
    "PLUGIN_MAP_PATH",
    "PluginMap",
    "load_plugin_map",
    "parse_plugin_map",
    "skill_directories",
]
