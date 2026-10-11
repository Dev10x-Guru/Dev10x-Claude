"""The shipped permission catalog is split into per-plugin fragments (GH-1551).

ADR-0034 Stage A3 keeps every fragment loaded by `dev10x`, so the split
must be invisible: the merged catalog is what the one-file original
declared, and `ensure-base` seeds every settings file byte-for-byte as
before. Only whole top-level sections move, because ensure-base appends
rules in catalog order and concatenating interleaved per-plugin rule
lists would reorder a freshly seeded file.
"""

from __future__ import annotations

import json
from pathlib import Path

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

#: Which top-level sections each plugin fragment owns. Everything else is
#: core and stays in projects.yaml.
FRAGMENT_SECTIONS = {
    "scoping": ["tracker_permissions"],
}


@pytest.fixture(scope="module")
def merged(projects_yaml: Path) -> dict:
    return load_catalog_document(catalog_path=projects_yaml)


@pytest.fixture(scope="module")
def projects_yaml() -> Path:
    return REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"


def test_fragment_layout_is_pinned(projects_yaml: Path) -> None:
    layout = {
        fragment.plugin: list(yaml.safe_load(fragment.path.read_text()))
        for fragment in catalog_fragments(catalog_path=projects_yaml)
    }
    assert layout == FRAGMENT_SECTIONS


def test_no_fragment_redefines_a_core_section(projects_yaml: Path) -> None:
    core = set(yaml.safe_load(projects_yaml.read_text()))
    moved = {section for sections in FRAGMENT_SECTIONS.values() for section in sections}
    assert core & moved == set()


def test_moved_tracker_rules_match_the_pre_split_catalog(merged: dict) -> None:
    expected = json.loads((SNAPSHOT / "tracker_permissions_pre_split.json").read_text())
    assert merged["tracker_permissions"] == expected
    assert list(merged["tracker_permissions"]) == list(expected)


def test_init_copy_parses_to_the_merged_catalog(projects_yaml: Path, merged: dict) -> None:
    assert yaml.safe_load(catalog_text(catalog_path=projects_yaml)) == merged


def test_every_reader_sees_the_scoping_fragment(projects_yaml: Path) -> None:
    config = parse_config(projects_yaml)
    assert config["tracker_permissions"]["github"][0] == "mcp__plugin_dev10x_cli__issue_get"
