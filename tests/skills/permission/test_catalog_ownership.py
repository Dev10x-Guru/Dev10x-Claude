"""Each Dev10x MCP allow lives in the fragment of the plugin that uses it (GH-1589).

A tool belongs to the plugin whose skills declare it in SKILL.md
``allowed-tools``. A tool declared by skills of several plugins, or by
none, stays in core: when the plugins ship separately, core is the one
every install has. The owner is recomputed here from the skill front
matter and ``plugins.yaml``, so a skill that starts or stops using a tool
fails this test until the rule moves with it.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
import yaml
from dev10x.skills.permission.catalog_paths import catalog_fragments

from dev10x.core.config.fragments import CORE_PLUGIN
from dev10x.core.plugin_map import load_plugin_map, skill_files
from dev10x.teach.skill_index.builder import extract_front_matter

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECTS_YAML = REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"
DEV10X_MCP_PREFIX = "mcp__plugin_dev10x_"

#: Tools whose owner is not decided by who declares them. `query` is the
#: db server's only tool; no skill lists it because db-psql reaches the
#: database through its own script.
OWNER_OVERRIDES = {
    "mcp__plugin_dev10x_db__query": "db",
}


def _declared_tools(*, skill_md: Path) -> list[str]:
    front_matter = extract_front_matter(skill_md.read_text()) or {}
    tools = front_matter.get("allowed-tools") or []
    return [str(tool).strip() for tool in tools]


def _tool_users() -> dict[str, set[str]]:
    plugin_map = load_plugin_map()
    users: dict[str, set[str]] = defaultdict(set)
    for skill_md in skill_files(repo_root=REPO_ROOT):
        plugin = plugin_map.plugin_for(skill=skill_md.parent.name)
        for tool in _declared_tools(skill_md=skill_md):
            users[tool].add(plugin)
    return users


def expected_owner(*, tool: str, users: dict[str, set[str]]) -> str:
    plugins = users.get(tool, set())
    single = next(iter(plugins)) if len(plugins) == 1 else CORE_PLUGIN
    return OWNER_OVERRIDES.get(tool, single)


def _rule_locations() -> dict[str, str]:
    files = [(CORE_PLUGIN, PROJECTS_YAML)] + [
        (fragment.plugin, fragment.path)
        for fragment in catalog_fragments(catalog_path=PROJECTS_YAML)
    ]
    return {
        rule: plugin
        for plugin, path in files
        for rule in (yaml.safe_load(path.read_text()) or {}).get("base_permissions", [])
        if rule.startswith(DEV10X_MCP_PREFIX)
    }


LOCATIONS = _rule_locations()
USERS = _tool_users()


@pytest.mark.parametrize("rule", sorted(LOCATIONS))
def test_mcp_allow_lives_in_its_owners_fragment(rule: str) -> None:
    assert LOCATIONS[rule] == expected_owner(tool=rule, users=USERS)


@pytest.mark.parametrize("tool", sorted(OWNER_OVERRIDES))
def test_every_override_names_a_catalogued_tool(tool: str) -> None:
    assert tool in LOCATIONS


class TestExpectedOwner:
    @pytest.mark.parametrize(
        ("users", "owner"),
        [
            ({"x": {"coding"}}, "coding"),
            ({"x": {"coding", "qa"}}, "core"),
            ({}, "core"),
        ],
    )
    def test_owner_follows_the_declaring_plugins(
        self, users: dict[str, set[str]], owner: str
    ) -> None:
        assert expected_owner(tool="x", users=users) == owner

    def test_an_override_wins(self) -> None:
        users = {"mcp__plugin_dev10x_db__query": {"coding"}}
        assert expected_owner(tool="mcp__plugin_dev10x_db__query", users=users) == "db"
