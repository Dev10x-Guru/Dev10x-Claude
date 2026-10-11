"""GH-1551: config fragments keyed by plugin merge back into one document."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.config.fragments import (
    ConfigFragment,
    FragmentError,
    discover_fragments,
    load_fragment,
    load_merged,
    merge_documents,
    plugin_order,
)
from dev10x.core.plugin_map import load_plugin_map

PLUGINS = ("core", "qa", "coding")


@pytest.fixture
def first_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "first"
    directory.mkdir()
    (directory / "coding.yaml").write_text("rules: [c1]\n")
    (directory / "core.yaml").write_text("rules: [k1]\n")
    return directory


@pytest.fixture
def second_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "second"
    directory.mkdir()
    (directory / "qa.yaml").write_text("rules: [q1]\n")
    (directory / "coding.yaml").write_text("rules: [c2]\n")
    return directory


class TestPluginOrder:
    def test_core_leads(self) -> None:
        assert plugin_order()[0] == "core"

    def test_follows_the_plugin_map_for_the_rest(self) -> None:
        expected = [name for name in load_plugin_map().plugins if name != "core"]
        assert list(plugin_order()[1:]) == expected


class TestDiscoverFragments:
    def test_orders_by_plugin_then_directory(self, first_dir: Path, second_dir: Path) -> None:
        found = discover_fragments(directories=[first_dir, second_dir], plugins=PLUGINS)
        assert found == [
            ConfigFragment(plugin="core", path=first_dir / "core.yaml"),
            ConfigFragment(plugin="qa", path=second_dir / "qa.yaml"),
            ConfigFragment(plugin="coding", path=first_dir / "coding.yaml"),
            ConfigFragment(plugin="coding", path=second_dir / "coding.yaml"),
        ]

    def test_skips_a_missing_directory(self, tmp_path: Path) -> None:
        assert discover_fragments(directories=[tmp_path / "absent"], plugins=PLUGINS) == []

    def test_refuses_a_fragment_named_after_no_plugin(self, tmp_path: Path) -> None:
        (tmp_path / "stray.yaml").write_text("rules: []\n")
        with pytest.raises(FragmentError, match="named after a plugin"):
            discover_fragments(directories=[tmp_path], plugins=PLUGINS)


class TestLoadFragment:
    def test_an_empty_file_is_an_empty_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "core.yaml"
        path.write_text("")
        assert load_fragment(path=path) == {}

    def test_refuses_a_non_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "core.yaml"
        path.write_text("- a\n")
        with pytest.raises(FragmentError, match="mapping"):
            load_fragment(path=path)


class TestMergeDocuments:
    @pytest.mark.parametrize(
        ("first", "second", "expected"),
        [
            ({"a": [1]}, {"a": [2]}, {"a": [1, 2]}),
            ({"a": {"x": [1]}}, {"a": {"x": [2], "y": [3]}}, {"a": {"x": [1, 2], "y": [3]}}),
            ({"a": 1}, {"b": 2}, {"a": 1, "b": 2}),
            ({"a": "same"}, {"a": "same"}, {"a": "same"}),
        ],
    )
    def test_merges(self, first: dict, second: dict, expected: dict) -> None:
        assert merge_documents(documents=[("one", first), ("two", second)]) == expected

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ({"a": 1}, {"a": 2}),
            ({"a": [1]}, {"a": {"x": 1}}),
            ({"a": {"b": 1}}, {"a": {"b": 2}}),
        ],
    )
    def test_refuses_a_conflict(self, first: dict, second: dict) -> None:
        with pytest.raises(FragmentError, match="conflicts"):
            merge_documents(documents=[("one", first), ("two", second)])

    def test_does_not_alias_its_inputs(self) -> None:
        first = {"a": [1]}
        merge_documents(documents=[("one", first), ("two", {"a": [2]})])
        assert first == {"a": [1]}


class TestLoadMerged:
    def test_base_leads_the_fragments(self, first_dir: Path, second_dir: Path) -> None:
        fragments = discover_fragments(directories=[first_dir, second_dir], plugins=PLUGINS)
        merged = load_merged(fragments=fragments, base=("base", {"rules": ["b0"]}))
        assert merged == {"rules": ["b0", "k1", "q1", "c1", "c2"]}

    def test_needs_no_base(self, first_dir: Path) -> None:
        fragments = discover_fragments(directories=[first_dir], plugins=PLUGINS)
        assert load_merged(fragments=fragments) == {"rules": ["k1", "c1"]}
