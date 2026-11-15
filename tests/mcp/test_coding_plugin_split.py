"""The MCP surface across the dev10x-coding split (ADR-0034 B9, GH-1572).

Two install shapes matter once the coding skills leave core:

- **Both plugins installed.** The full tool list is the pre-move list,
  name for name, and every script a coding tool runs resolves into the
  ``dev10x-coding`` tree, whether that sits under a checkout
  (``plugins/coding``) or in the cache beside core.
- **Only core installed.** No coding skill ships, so neither the skills
  nor the scripts behind the coding tools are present, and a coding
  script lookup names the ``plugins/coding`` path it expected.

Core's ``cli`` server keeps registering the ``dev10x.coding`` tools in both
shapes. That is the supervisor's GH-1563 decision (ADR-0034 Stage B
decision 3): the optional shared MCP daemon serves several projects from
one tool list fixed at startup, so registration cannot follow a
per-project install. ``TestCoreOnly`` pins that accepted cost explicitly
rather than leaving it implicit.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
from pathlib import Path

import pytest

from dev10x.coding.coding_script import CODING_KEY, CODING_PLUGIN_NAME
from dev10x.coding.mcp.registration import TOOL_MODULES as CODING_TOOL_MODULES
from dev10x.core.paths import PLUGIN_MANIFEST, satellite_script, skill_script
from dev10x.core.plugin_map import load_plugin_map
from dev10x.core.skills.playbook.discovery import installed_plugin_roots
from dev10x.core.subprocess_utils import get_plugin_root
from dev10x.db.mcp.server_db import server as db_server
from dev10x.mcp.server_cli import server as cli_server

PRE_MOVE_NAMES = Path(__file__).parents[1] / "fixtures" / "mcp_tool_names_pre_b9.json"
CORE_VERSION = "0.116.0"
CORE_MANIFEST = '{"name": "dev10x"}'
CODING_MANIFEST = json.dumps({"name": CODING_PLUGIN_NAME})


async def _tool_names() -> dict[str, list[str]]:
    return {
        "cli": sorted(tool.name for tool in await cli_server.list_tools()),
        "db": sorted(tool.name for tool in await db_server.list_tools()),
    }


def _coding_script_calls() -> list[tuple[str, str]]:
    """Every literal ``coding_script(skill=..., rel=...)`` call in ``src/``."""
    calls = set()
    for path in (get_plugin_root() / "src" / "dev10x").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "coding_script"
            ):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            skill, rel = kwargs.get("skill"), kwargs.get("rel")
            if isinstance(skill, ast.Constant) and isinstance(rel, ast.Constant):
                calls.add((skill.value, rel.value))
    return sorted(calls)


def _resolve(*, core_root: Path, skill: str, rel: str) -> str:
    return satellite_script(
        plugin_root=core_root,
        key=CODING_KEY,
        plugin_name=CODING_PLUGIN_NAME,
        skill=skill,
        rel=rel,
    )


def _write(*, path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture(scope="module")
def tool_names() -> dict[str, list[str]]:
    return asyncio.run(_tool_names())


@pytest.fixture(scope="module")
def coding_tool_names(tool_names: dict[str, list[str]]) -> set[str]:
    modules = [importlib.import_module(name) for name in CODING_TOOL_MODULES]
    return {
        name
        for name in tool_names["cli"]
        if any(callable(getattr(module, name, None)) for module in modules)
    }


@pytest.fixture(scope="module")
def script_calls() -> list[tuple[str, str]]:
    calls = _coding_script_calls()
    assert calls, "no coding_script() call found; the scan stopped matching"
    return calls


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "Dev10x-Guru"


@pytest.fixture
def core_root(cache: Path) -> Path:
    root = cache / "dev10x" / CORE_VERSION
    _write(path=root / PLUGIN_MANIFEST, text=CORE_MANIFEST)
    return root


class TestBothPluginsInstalled:
    def test_tool_list_is_the_pre_move_list(self, tool_names: dict[str, list[str]]) -> None:
        assert tool_names == json.loads(PRE_MOVE_NAMES.read_text())

    def test_coding_tools_register_in_the_core_cli_server(
        self, coding_tool_names: set[str]
    ) -> None:
        assert {"push_safe", "create_pr", "ci_check_status", "collect_prs"} <= coding_tool_names

    def test_checkout_scripts_resolve_under_plugins_coding(
        self, script_calls: list[tuple[str, str]]
    ) -> None:
        root = get_plugin_root()
        resolved = [_resolve(core_root=root, skill=skill, rel=rel) for skill, rel in script_calls]

        assert [path for path in resolved if not (root / path).is_file()] == []
        assert all(path.startswith("plugins/coding/skills/") for path in resolved)

    def test_installed_scripts_resolve_beside_core(
        self,
        cache: Path,
        core_root: Path,
        script_calls: list[tuple[str, str]],
    ) -> None:
        satellite = cache / CODING_PLUGIN_NAME / CORE_VERSION
        _write(path=satellite / PLUGIN_MANIFEST, text=CODING_MANIFEST)
        for skill, rel in script_calls:
            _write(path=satellite / skill_script(skill=skill, rel=rel), text="")

        resolved = [
            _resolve(core_root=core_root, skill=skill, rel=rel) for skill, rel in script_calls
        ]

        assert resolved == [
            str(satellite / skill_script(skill=skill, rel=rel)) for skill, rel in script_calls
        ]

    def test_playbook_readers_see_the_coding_tree(self, cache: Path, core_root: Path) -> None:
        satellite = cache / CODING_PLUGIN_NAME / CORE_VERSION
        _write(path=satellite / PLUGIN_MANIFEST, text=CODING_MANIFEST)

        assert installed_plugin_roots(core_root=core_root) == [core_root, satellite]


class TestCoreOnly:
    def test_core_ships_no_coding_skill(self) -> None:
        shipped = {path.name for path in (get_plugin_root() / "skills").iterdir()}

        assert shipped & set(load_plugin_map().plugins[CODING_KEY]) == set()

    def test_core_ships_exactly_its_own_skills(self) -> None:
        shipped = {path.parent.name for path in (get_plugin_root() / "skills").glob("*/SKILL.md")}

        assert shipped == set(load_plugin_map().plugins["core"])

    def test_coding_scripts_are_absent(
        self,
        core_root: Path,
        script_calls: list[tuple[str, str]],
    ) -> None:
        resolved = [
            _resolve(core_root=core_root, skill=skill, rel=rel) for skill, rel in script_calls
        ]

        assert [path for path in resolved if (core_root / path).exists()] == []
        assert all(path.startswith("plugins/coding/skills/") for path in resolved)

    def test_playbook_readers_see_only_core(self, core_root: Path) -> None:
        assert installed_plugin_roots(core_root=core_root) == [core_root]

    def test_coding_tools_stay_registered_by_decision_gh_1563(
        self,
        tool_names: dict[str, list[str]],
        coding_tool_names: set[str],
    ) -> None:
        assert coding_tool_names <= set(tool_names["cli"])
