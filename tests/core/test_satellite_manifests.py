from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.core.paths import SATELLITES_DIR
from dev10x.core.plugin_map import CORE_KEY, PluginMap, load_plugin_map, parse_plugin_map
from dev10x.subprocess_utils import get_plugin_root

MANIFEST = Path(".claude-plugin") / "plugin.json"


def satellite_manifests(*, repo_root: Path) -> dict[str, dict]:
    return {
        path.parent.parent.name: json.loads(path.read_text())
        for path in sorted((repo_root / SATELLITES_DIR).glob(f"*/{MANIFEST}"))
    }


def dependency_drift(*, manifests: dict[str, dict], plugin_map: PluginMap) -> list[str]:
    drift = []
    for directory, manifest in manifests.items():
        name = manifest.get("name", "")
        key = plugin_map.key_for_plugin_name(name=name)
        if key in {None, CORE_KEY}:
            drift.append(f"{directory}: {name!r} is not a satellite in plugins.yaml")
            continue
        expected = plugin_map.manifest_dependencies(key=key)
        if manifest.get("dependencies") != expected:
            drift.append(f"{directory}: {manifest.get('dependencies')} != {expected}")
    return drift


@pytest.fixture(scope="module")
def plugin_map() -> PluginMap:
    return load_plugin_map()


@pytest.fixture
def toy_map() -> PluginMap:
    return parse_plugin_map(
        data={
            "plugins": {"core": [], "coding": [], "tasks": [], "qa": []},
            "plugin_names": {
                "core": "dev10x",
                "coding": "dev10x-coding",
                "tasks": "dev10x-tasks",
                "qa": "dev10x-qa",
            },
            "dependencies": {"coding": ["tasks"]},
            "soft_dependencies": {"qa": ["coding"]},
        }
    )


class TestRepositoryManifests:
    def test_satellite_manifests_declare_the_derived_dependencies(
        self,
        plugin_map: PluginMap,
    ) -> None:
        manifests = satellite_manifests(repo_root=get_plugin_root())

        assert dependency_drift(manifests=manifests, plugin_map=plugin_map) == []

    def test_every_extracted_plugin_ships_a_manifest(self, plugin_map: PluginMap) -> None:
        names = {
            manifest.get("name")
            for manifest in satellite_manifests(repo_root=get_plugin_root()).values()
        }

        assert [
            key for key in plugin_map.extracted if plugin_map.plugin_name(key=key) not in names
        ] == []

    @pytest.mark.parametrize(
        ("key", "expected"),
        [("qa", ["dev10x"]), ("coding", ["dev10x", "dev10x-tasks"]), ("core", [])],
    )
    def test_shipped_map_derivation(
        self,
        plugin_map: PluginMap,
        key: str,
        expected: list[str],
    ) -> None:
        assert plugin_map.manifest_dependencies(key=key) == expected


class TestManifestDependencies:
    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            pytest.param("core", [], id="core-declares-nothing"),
            pytest.param("qa", ["dev10x"], id="soft-edge-not-emitted"),
            pytest.param("coding", ["dev10x", "dev10x-tasks"], id="hard-edge-mapped"),
            pytest.param("tasks", ["dev10x"], id="core-only"),
        ],
    )
    def test_manifest_dependencies(
        self, toy_map: PluginMap, key: str, expected: list[str]
    ) -> None:
        assert toy_map.manifest_dependencies(key=key) == expected

    def test_an_unnamed_dependency_falls_back_to_the_scheme_name(self) -> None:
        mapped = parse_plugin_map(data={"dependencies": {"coding": ["tasks"]}})

        assert mapped.manifest_dependencies(key="coding") == ["dev10x", "dev10x-tasks"]

    @pytest.mark.parametrize(("name", "expected"), [("dev10x-qa", "qa"), ("dev10x-ghost", None)])
    def test_key_for_plugin_name(
        self, toy_map: PluginMap, name: str, expected: str | None
    ) -> None:
        assert toy_map.key_for_plugin_name(name=name) == expected


class TestDependencyDrift:
    @pytest.mark.parametrize(
        ("manifest", "expected"),
        [
            pytest.param({"name": "dev10x-qa", "dependencies": ["dev10x"]}, [], id="agrees"),
            pytest.param(
                {"name": "dev10x-qa"},
                ["qa: None != ['dev10x']"],
                id="missing-dependencies",
            ),
            pytest.param(
                {"name": "dev10x-qa", "dependencies": ["dev10x", "dev10x-coding"]},
                ["qa: ['dev10x', 'dev10x-coding'] != ['dev10x']"],
                id="soft-edge-emitted",
            ),
            pytest.param(
                {"name": "dev10x-ghost", "dependencies": ["dev10x"]},
                ["qa: 'dev10x-ghost' is not a satellite in plugins.yaml"],
                id="unknown-plugin-name",
            ),
            pytest.param(
                {"name": "dev10x", "dependencies": []},
                ["qa: 'dev10x' is not a satellite in plugins.yaml"],
                id="core",
            ),
        ],
    )
    def test_dependency_drift(
        self, toy_map: PluginMap, manifest: dict, expected: list[str]
    ) -> None:
        assert dependency_drift(manifests={"qa": manifest}, plugin_map=toy_map) == expected

    def test_reads_manifests_under_plugins(self, tmp_path: Path) -> None:
        manifest = tmp_path / "plugins" / "qa" / MANIFEST
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"name": "dev10x-qa"}')
        (tmp_path / "plugins" / "loose").mkdir()

        assert satellite_manifests(repo_root=tmp_path) == {"qa": {"name": "dev10x-qa"}}
