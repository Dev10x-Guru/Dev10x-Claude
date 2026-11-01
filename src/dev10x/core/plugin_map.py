"""Skill-to-plugin assignment for the staged plugin split (ADR-0034, GH-1524)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dev10x.core.paths import SKILLS_DIR

PLUGIN_MAP_PATH = Path(__file__).with_name("plugins.yaml")
CORE_PLUGIN_NAME = "dev10x"
SATELLITE_NAME_PREFIX = f"{CORE_PLUGIN_NAME}-"
SATELLITES_DIR = "plugins"
SKILL_FILE = "SKILL.md"


def expected_plugin_name(*, key: str) -> str:
    return CORE_PLUGIN_NAME if key == "core" else f"{SATELLITE_NAME_PREFIX}{key}"


@dataclass(frozen=True)
class PluginMap:
    plugins: dict[str, tuple[str, ...]]
    plugin_names: dict[str, str] = field(default_factory=dict)
    marketplace: str = ""
    extracted: tuple[str, ...] = ()
    dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    soft_dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def plugin_name(self, *, key: str) -> str | None:
        return self.plugin_names.get(key)

    def is_extracted(self, *, key: str) -> bool:
        return key in self.extracted

    def unknown_extracted(self) -> list[str]:
        return sorted(set(self.extracted) - set(self.plugins))

    def unknown_dependency_keys(self) -> list[str]:
        return _unknown_keys(edges=self.dependencies, known=set(self.plugins))

    def unknown_soft_dependency_keys(self) -> list[str]:
        return _unknown_keys(edges=self.soft_dependencies, known=set(self.plugins))

    def dependency_cycle(self) -> list[str]:
        for start in sorted(self.dependencies):
            cycle = self._cycle_from(path=(start,))
            if cycle:
                return cycle
        return []

    def _cycle_from(self, *, path: tuple[str, ...]) -> list[str]:
        for nxt in self.dependencies.get(path[-1], ()):
            if nxt in path:
                return [*path[path.index(nxt) :], nxt]
            cycle = self._cycle_from(path=(*path, nxt))
            if cycle:
                return cycle
        return []

    def known_plugin_names(self) -> tuple[str, ...]:
        return tuple(self.plugin_names.values())

    def unnamed_plugins(self) -> list[str]:
        return sorted(set(self.plugins) - set(self.plugin_names))

    def names_off_scheme(self) -> list[str]:
        return sorted(
            key for key, name in self.plugin_names.items() if name != expected_plugin_name(key=key)
        )

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


def _unknown_keys(*, edges: dict[str, tuple[str, ...]], known: set[str]) -> list[str]:
    named = set(edges) | {target for targets in edges.values() for target in targets}
    return sorted(named - known)


def _edge_map(*, raw: Any) -> dict[str, tuple[str, ...]]:
    return {key: tuple(targets or ()) for key, targets in (raw or {}).items()}


def parse_plugin_map(*, data: dict[str, Any]) -> PluginMap:
    plugins = data.get("plugins") or {}
    return PluginMap(
        plugins={plugin: tuple(skills or ()) for plugin, skills in plugins.items()},
        plugin_names=dict(data.get("plugin_names") or {}),
        marketplace=str(data.get("marketplace") or ""),
        extracted=tuple(data.get("extracted") or ()),
        dependencies=_edge_map(raw=data.get("dependencies")),
        soft_dependencies=_edge_map(raw=data.get("soft_dependencies")),
    )


def load_plugin_map(*, path: Path = PLUGIN_MAP_PATH) -> PluginMap:
    return parse_plugin_map(data=yaml.safe_load(path.read_text()) or {})


def skill_directories(*, skills_root: Path) -> list[str]:
    return sorted(
        entry.name
        for entry in skills_root.iterdir()
        if entry.is_dir() and (entry / SKILL_FILE).is_file()
    )


def skill_roots(*, repo_root: Path) -> list[Path]:
    satellites = sorted(
        path for path in (repo_root / SATELLITES_DIR).glob(f"*/{SKILLS_DIR}") if path.is_dir()
    )
    return [repo_root / SKILLS_DIR, *satellites]


def skill_files(*, repo_root: Path) -> list[Path]:
    return [
        skill_file
        for root in skill_roots(repo_root=repo_root)
        for skill_file in sorted(root.glob(f"*/{SKILL_FILE}"))
    ]


def repo_skill_directories(*, repo_root: Path) -> list[str]:
    return sorted(skill_file.parent.name for skill_file in skill_files(repo_root=repo_root))


__all__ = [
    "CORE_PLUGIN_NAME",
    "PLUGIN_MAP_PATH",
    "SATELLITES_DIR",
    "SATELLITE_NAME_PREFIX",
    "SKILL_FILE",
    "PluginMap",
    "expected_plugin_name",
    "load_plugin_map",
    "parse_plugin_map",
    "repo_skill_directories",
    "skill_directories",
    "skill_files",
    "skill_roots",
]
