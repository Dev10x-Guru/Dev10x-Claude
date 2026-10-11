"""Cross-plugin skill-folder paths in SKILL.md files (ADR-0034 Stage A3, GH-1553).

A skill that names ``${CLAUDE_PLUGIN_ROOT}/skills/<other>/`` reaches into
another skill's folder. Inside one plugin that is harmless; once Stage B
gives each plugin its own root, a path into a sibling plugin stops
resolving. A skill may therefore reach only its own plugin's folders or
core's, mirroring the Python import boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dev10x.core.plugin_map import PluginMap

CORE_PLUGIN = "core"
SKILL_FILE = "SKILL.md"
SKILL_FOLDER_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/skills/([a-z0-9][a-z0-9-]*)/")


@dataclass(frozen=True, order=True)
class SkillPathEdge:
    skill: str
    target: str


def skill_folder_targets(*, text: str) -> list[str]:
    return sorted(set(SKILL_FOLDER_PATH.findall(text)))


def cross_plugin_edges(*, skills_root: Path, plugin_map: PluginMap) -> list[SkillPathEdge]:
    edges: list[SkillPathEdge] = []
    for skill_file in sorted(skills_root.glob(f"*/{SKILL_FILE}")):
        skill = skill_file.parent.name
        own = plugin_map.plugin_for(skill=skill)
        for target in skill_folder_targets(text=skill_file.read_text()):
            if plugin_map.plugin_for(skill=target) not in {own, CORE_PLUGIN}:
                edges.append(SkillPathEdge(skill=skill, target=target))
    return edges


__all__ = [
    "SKILL_FOLDER_PATH",
    "SkillPathEdge",
    "cross_plugin_edges",
    "skill_folder_targets",
]
