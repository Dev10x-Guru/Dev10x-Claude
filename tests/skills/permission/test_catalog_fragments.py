"""The shipped permission catalog is split into per-plugin fragments (GH-1551, GH-1589).

ADR-0034 Stage A3 keeps every fragment loaded by `dev10x`, so the split
must not lose or invent a rule: for every list in the catalog, the merged
multiset equals what the one-file original declared. Order is allowed to
change — the supervisor accepted that ensure-base appends rules in merged
order (core first, then plugins.yaml order) rather than the pre-split one.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from dev10x.skills.permission.catalog_paths import (
    catalog_fragments,
    catalog_text,
    load_catalog_document,
)
from dev10x.skills.permission.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "permission_catalog"
PRE_SPLIT_LISTS = SNAPSHOT / "catalog_lists_pre_split.json"

SAFETY_FLOOR_SECTIONS = ("base_asks", "base_denies", "tracker_denies", "ide_denies")


def _canonical(*, item: Any) -> str:
    return item if isinstance(item, str) else json.dumps(item, sort_keys=True)


def catalog_lists(*, document: dict[str, Any]) -> dict[str, list[str]]:
    """Every list in the catalog, one level of nesting deep, sorted.

    Sorting is the point: it compares the multiset, so a moved rule
    passes and a dropped or duplicated one does not.
    """
    lists: dict[str, list[str]] = {}
    for key, value in document.items():
        nested = value if isinstance(value, dict) else {"": value}
        for sub, items in nested.items():
            if isinstance(items, list):
                dotted = f"{key}.{sub}" if sub else key
                lists[dotted] = sorted(_canonical(item=item) for item in items)
    return lists


@pytest.fixture(scope="module")
def projects_yaml() -> Path:
    return REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"


@pytest.fixture(scope="module")
def merged(projects_yaml: Path) -> dict:
    return load_catalog_document(catalog_path=projects_yaml)


@pytest.fixture(scope="module")
def merged_lists(merged: dict) -> dict[str, list[str]]:
    return catalog_lists(document=merged)


def test_fragment_plugins_are_pinned(projects_yaml: Path) -> None:
    plugins = [fragment.plugin for fragment in catalog_fragments(catalog_path=projects_yaml)]
    assert plugins == ["qa", "db", "comm", "teach", "tasks", "scoping", "coding"]


def test_every_list_matches_the_pre_split_catalog(merged_lists: dict[str, list[str]]) -> None:
    expected = json.loads(PRE_SPLIT_LISTS.read_text())
    assert merged_lists == expected


@pytest.mark.parametrize("key", json.loads(PRE_SPLIT_LISTS.read_text()))
def test_no_list_carries_a_duplicate(merged_lists: dict[str, list[str]], key: str) -> None:
    duplicates = [item for item, count in Counter(merged_lists[key]).items() if count > 1]
    assert duplicates == []


@pytest.mark.parametrize("section", SAFETY_FLOOR_SECTIONS)
def test_the_safety_floor_stays_in_core(projects_yaml: Path, section: str) -> None:
    fragment_sections = {
        key
        for fragment in catalog_fragments(catalog_path=projects_yaml)
        for key in yaml.safe_load(fragment.path.read_text())
    }
    assert section not in fragment_sections


def test_scalars_survive_the_split(merged: dict) -> None:
    assert merged["plugin_cache"] == "~/.claude/plugins/cache/Dev10x-Guru/Dev10x"
    assert merged["include_user_settings"] is True


def test_moved_tracker_rules_match_the_pre_split_catalog(merged: dict) -> None:
    expected = json.loads((SNAPSHOT / "tracker_permissions_pre_split.json").read_text())
    assert merged["tracker_permissions"] == expected
    assert list(merged["tracker_permissions"]) == list(expected)


def test_init_copy_parses_to_the_merged_catalog(projects_yaml: Path, merged: dict) -> None:
    assert yaml.safe_load(catalog_text(catalog_path=projects_yaml)) == merged


def test_init_copy_keeps_the_catalog_header(projects_yaml: Path) -> None:
    header = projects_yaml.read_text().split("\n\n", 1)[0]
    assert catalog_text(catalog_path=projects_yaml).startswith(header)


def test_every_reader_sees_the_scoping_fragment(projects_yaml: Path) -> None:
    config = parse_config(projects_yaml)
    assert config["tracker_permissions"]["github"][0] == "mcp__plugin_dev10x_cli__issue_get"


def test_every_reader_sees_rules_from_plugin_fragments(projects_yaml: Path) -> None:
    rules = parse_config(projects_yaml)["base_permissions"]
    assert "mcp__plugin_dev10x_cli__create_pr" in rules
    assert "Bash(dev10x foreman probe:*)" in rules
