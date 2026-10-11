from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.plugin_map import PluginMap, load_plugin_map, parse_plugin_map
from dev10x.core.skill_path_edges import (
    SkillPathEdge,
    cross_plugin_edges,
    skill_folder_targets,
)
from dev10x.subprocess_utils import get_plugin_root

# Each entry is a known edge with the issue that removes it.
KNOWN_EDGES: dict[SkillPathEdge, str] = {}


@pytest.fixture
def toy_map() -> PluginMap:
    return parse_plugin_map(
        data={
            "plugins": {
                "core": ["helper"],
                "scoping": ["ticket", "spec"],
                "coding": ["pr"],
            }
        }
    )


@pytest.fixture
def toy_skills(tmp_path: Path) -> Path:
    bodies = {
        "ticket": (
            "  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/pr/scripts/:*)\n"
            "  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/helper/scripts/:*)\n"
            "  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/spec/scripts/:*)\n"
        ),
        "pr": "  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/helper/scripts/:*)\n",
        "helper": "run ${CLAUDE_PLUGIN_ROOT}/skills/pr/x.sh\n",
    }
    for skill, body in bodies.items():
        (tmp_path / skill).mkdir()
        (tmp_path / skill / "SKILL.md").write_text(body)
    return tmp_path


class TestRepositoryEdges:
    def test_only_known_edges_cross_plugins(self) -> None:
        edges = cross_plugin_edges(
            skills_root=get_plugin_root() / "skills",
            plugin_map=load_plugin_map(),
        )

        assert edges == sorted(KNOWN_EDGES)

    @pytest.mark.parametrize("skill", ["ticket-create", "ticket-jtbd", "project-scope"])
    def test_ticket_skills_reach_no_coding_folder(self, skill: str) -> None:
        plugin_map = load_plugin_map()
        text = (get_plugin_root() / "skills" / skill / "SKILL.md").read_text()

        targets = {
            plugin_map.plugin_for(skill=target) for target in skill_folder_targets(text=text)
        }

        assert "coding" not in targets


class TestCrossPluginEdges:
    def test_flags_only_sibling_plugin_targets(self, toy_skills: Path, toy_map: PluginMap) -> None:
        assert cross_plugin_edges(skills_root=toy_skills, plugin_map=toy_map) == [
            SkillPathEdge(skill="helper", target="pr"),
            SkillPathEdge(skill="ticket", target="pr"),
        ]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)", ["gh-context"]),
            ("${CLAUDE_PLUGIN_ROOT}/skills/b/x ${CLAUDE_PLUGIN_ROOT}/skills/a/y", ["a", "b"]),
            ("skills/gh-context/scripts/gh-pr-get.sh", []),
            ("${CLAUDE_PLUGIN_ROOT}/hooks/x", []),
        ],
    )
    def test_skill_folder_targets(self, text: str, expected: list[str]) -> None:
        assert skill_folder_targets(text=text) == expected
