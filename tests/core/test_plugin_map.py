from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.plugin_map import (
    PluginMap,
    expected_plugin_name,
    load_plugin_map,
    parse_plugin_map,
    repo_skill_directories,
    skill_directories,
)
from dev10x.subprocess_utils import get_plugin_root

ADR_0034_COUNTS = {
    "qa": 6,
    "infra": 2,
    "db": 3,
    "comm": 7,
    "teach": 7,
    "tasks": 7,
    "scoping": 17,
    "core": 17,
    "coding": 38,
}


@pytest.fixture(scope="module")
def plugin_map() -> PluginMap:
    return load_plugin_map()


@pytest.fixture(scope="module")
def skill_dirs() -> list[str]:
    return repo_skill_directories(repo_root=get_plugin_root())


@pytest.fixture
def toy_map() -> PluginMap:
    return parse_plugin_map(data={"plugins": {"qa": ["tts", "tts"], "core": ["afk", "ghost"]}})


class TestRepositoryPluginMap:
    def test_every_skill_directory_is_assigned(
        self,
        plugin_map: PluginMap,
        skill_dirs: list[str],
    ) -> None:
        assert plugin_map.unassigned_skills(skill_dirs=skill_dirs) == []

    def test_no_skill_is_assigned_twice(self, plugin_map: PluginMap) -> None:
        assert plugin_map.duplicated_skills() == []

    def test_no_entry_names_a_missing_directory(
        self,
        plugin_map: PluginMap,
        skill_dirs: list[str],
    ) -> None:
        assert plugin_map.unknown_skills(skill_dirs=skill_dirs) == []

    def test_counts_match_adr_0034(self, plugin_map: PluginMap) -> None:
        assert plugin_map.counts() == ADR_0034_COUNTS

    def test_counts_sum_to_the_skill_total(
        self,
        plugin_map: PluginMap,
        skill_dirs: list[str],
    ) -> None:
        assert sum(plugin_map.counts().values()) == len(skill_dirs)

    def test_every_plugin_has_a_name(self, plugin_map: PluginMap) -> None:
        assert plugin_map.unnamed_plugins() == []

    def test_names_follow_the_dev10x_area_scheme(self, plugin_map: PluginMap) -> None:
        assert plugin_map.names_off_scheme() == []

    def test_names_are_keyed_by_plugin_only(self, plugin_map: PluginMap) -> None:
        assert set(plugin_map.plugin_names) == set(plugin_map.plugins)

    def test_marketplace_is_the_core_install_marketplace(self, plugin_map: PluginMap) -> None:
        assert plugin_map.marketplace == "Dev10x-Guru"

    def test_nothing_is_extracted_during_stage_a(self, plugin_map: PluginMap) -> None:
        assert plugin_map.extracted == ()

    def test_extracted_keys_are_known_plugins(self, plugin_map: PluginMap) -> None:
        assert plugin_map.unknown_extracted() == []

    def test_hard_dependencies_name_known_plugins(self, plugin_map: PluginMap) -> None:
        assert plugin_map.unknown_dependency_keys() == []

    def test_core_declares_no_dependencies(self, plugin_map: PluginMap) -> None:
        assert "core" not in plugin_map.dependencies

    def test_hard_dependencies_are_acyclic(self, plugin_map: PluginMap) -> None:
        assert plugin_map.dependency_cycle() == []

    def test_coding_depends_on_tasks(self, plugin_map: PluginMap) -> None:
        assert plugin_map.dependencies == {"coding": ("tasks",)}

    def test_soft_dependencies_name_known_plugins(self, plugin_map: PluginMap) -> None:
        assert plugin_map.unknown_soft_dependency_keys() == []


class TestPluginDependencies:
    @pytest.mark.parametrize(
        ("dependencies", "expected"),
        [
            pytest.param({"a": ["b"], "b": ["c"]}, [], id="chain"),
            pytest.param({"a": ["b", "c"], "b": ["c"]}, [], id="diamond"),
            pytest.param({"a": ["a"]}, ["a", "a"], id="self-loop"),
            pytest.param({"a": ["b"], "b": ["c"], "c": ["b"]}, ["b", "c", "b"], id="loop"),
        ],
    )
    def test_dependency_cycle(self, dependencies: dict, expected: list[str]) -> None:
        assert parse_plugin_map(data={"dependencies": dependencies}).dependency_cycle() == expected

    def test_flags_unknown_dependency_keys(self) -> None:
        mapped = parse_plugin_map(
            data={"plugins": {"coding": [], "tasks": []}, "dependencies": {"coding": ["ghost"]}}
        )
        assert mapped.unknown_dependency_keys() == ["ghost"]

    def test_flags_unknown_soft_dependency_keys(self) -> None:
        mapped = parse_plugin_map(
            data={"plugins": {"qa": []}, "soft_dependencies": {"qa": ["coding"], "x": None}}
        )
        assert mapped.unknown_soft_dependency_keys() == ["coding", "x"]

    @pytest.mark.parametrize(("key", "expected"), [("qa", True), ("db", False)])
    def test_is_extracted(self, key: str, expected: bool) -> None:
        mapped = parse_plugin_map(data={"plugins": {"qa": [], "db": []}, "extracted": ["qa"]})
        assert mapped.is_extracted(key=key) is expected

    def test_flags_an_unknown_extracted_key(self) -> None:
        mapped = parse_plugin_map(data={"plugins": {"qa": []}, "extracted": ["qa", "ghost"]})
        assert mapped.unknown_extracted() == ["ghost"]

    def test_missing_sections_parse_to_empty(self) -> None:
        mapped = parse_plugin_map(data={})
        assert (mapped.marketplace, mapped.extracted, mapped.dependencies) == ("", (), {})


class TestPluginNames:
    @pytest.fixture
    def named_map(self) -> PluginMap:
        return parse_plugin_map(
            data={
                "plugin_names": {"core": "dev10x", "qa": "qa-plugin"},
                "plugins": {"core": ["afk"], "qa": ["tts"], "comm": ["gog"]},
            }
        )

    @pytest.mark.parametrize(
        ("key", "expected"),
        [("core", "dev10x"), ("qa", "dev10x-qa"), ("teach", "dev10x-teach")],
    )
    def test_expected_plugin_name(self, key: str, expected: str) -> None:
        assert expected_plugin_name(key=key) == expected

    @pytest.mark.parametrize(
        ("key", "expected"),
        [("core", "dev10x"), ("qa", "qa-plugin"), ("comm", None)],
    )
    def test_plugin_name(self, named_map: PluginMap, key: str, expected: str | None) -> None:
        assert named_map.plugin_name(key=key) == expected

    def test_known_plugin_names(self, named_map: PluginMap) -> None:
        assert named_map.known_plugin_names() == ("dev10x", "qa-plugin")

    def test_flags_an_unnamed_plugin(self, named_map: PluginMap) -> None:
        assert named_map.unnamed_plugins() == ["comm"]

    def test_flags_a_name_off_scheme(self, named_map: PluginMap) -> None:
        assert named_map.names_off_scheme() == ["qa"]

    def test_missing_names_parse_to_empty(self) -> None:
        assert parse_plugin_map(data={"plugins": {"qa": ["tts"]}}).plugin_names == {}


class TestPluginMapDetectors:
    def test_flags_a_new_unassigned_directory(self, toy_map: PluginMap) -> None:
        assert toy_map.unassigned_skills(skill_dirs=["tts", "afk", "brand-new"]) == ["brand-new"]

    def test_flags_a_duplicate(self, toy_map: PluginMap) -> None:
        assert toy_map.duplicated_skills() == ["tts"]

    def test_flags_an_entry_without_a_directory(self, toy_map: PluginMap) -> None:
        assert toy_map.unknown_skills(skill_dirs=["tts", "afk"]) == ["ghost"]

    @pytest.mark.parametrize(
        ("skill", "expected"),
        [("afk", "core"), ("tts", "qa"), ("nowhere", None)],
    )
    def test_plugin_for(self, toy_map: PluginMap, skill: str, expected: str | None) -> None:
        assert toy_map.plugin_for(skill=skill) == expected

    def test_empty_document_parses_to_no_plugins(self) -> None:
        assert parse_plugin_map(data={}).plugins == {}


class TestSkillDirectories:
    def test_lists_only_directories_holding_a_skill(self, tmp_path: Path) -> None:
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "SKILL.md").write_text("---\n")
        (tmp_path / "empty").mkdir()
        (tmp_path / "loose.md").write_text("")

        assert skill_directories(skills_root=tmp_path) == ["real"]

    def test_repo_skill_directories_merge_every_root(self, split_repo: Path) -> None:
        assert repo_skill_directories(repo_root=split_repo) == ["afk", "k8s", "tts"]
