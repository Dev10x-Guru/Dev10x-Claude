"""Tests for tracker resolution and the shipped tracker catalog (GH-768)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.tracker_choice import (
    Tracker,
    apply_tracker_selection,
    tracker_inventory,
)
from dev10x.skills.permission.tracker_resolve import resolve_tracker, tracker_source

_PROJECTS_YAML = (
    Path(__file__).resolve().parents[3] / "skills" / "upgrade-cleanup" / "projects.yaml"
)


@pytest.fixture
def friction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "friction.yaml"
    monkeypatch.setattr(
        "dev10x.domain.documents.session_yaml.Dev10xConfigDir.friction_yaml",
        classmethod(lambda cls: path),
    )
    return path


def _write(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


class TestResolveTracker:
    def test_no_config_falls_back_to_default(self, friction: Path) -> None:
        assert resolve_tracker(toplevel="/work/x/repo") is Tracker.LINEAR
        assert tracker_source(toplevel="/work/x/repo") == "default"

    def test_no_toplevel_falls_back_to_default(self, friction: Path) -> None:
        assert resolve_tracker(toplevel=None) is Tracker.LINEAR
        assert tracker_source(toplevel=None) == "default"

    def test_project_entry_wins(self, friction: Path, tmp_path: Path) -> None:
        root = str(tmp_path / "repo")
        _write(
            friction,
            {
                "defaults": {"tracker": "github"},
                "projects": [{"match": [root], "tracker": "jira"}],
            },
        )
        assert resolve_tracker(toplevel=root) is Tracker.JIRA
        assert tracker_source(toplevel=root) == "project"

    def test_defaults_apply_when_no_project_matches(self, friction: Path, tmp_path: Path) -> None:
        _write(friction, {"defaults": {"tracker": "github"}})
        root = str(tmp_path / "repo")
        assert resolve_tracker(toplevel=root) is Tracker.GITHUB
        assert tracker_source(toplevel=root) == "defaults"

    def test_unrecognised_value_degrades_to_default(self, friction: Path, tmp_path: Path) -> None:
        """A typo must not blow up a seeding run mid-flight."""
        root = str(tmp_path / "repo")
        _write(friction, {"projects": [{"match": [root], "tracker": "gitlab"}]})
        assert resolve_tracker(toplevel=root) is Tracker.LINEAR
        assert tracker_source(toplevel=root) == "default"


class TestShippedCatalog:
    @pytest.fixture
    def catalog(self) -> dict:
        return yaml.safe_load(_PROJECTS_YAML.read_text())

    def test_every_tracker_has_a_block(self, catalog: dict) -> None:
        inventory = tracker_inventory(config=catalog)
        assert all(inventory[tracker] for tracker in Tracker)

    def test_flat_catalog_no_longer_seeds_linear_unconditionally(self, catalog: dict) -> None:
        """The GH-768 defect: a Jira user collected ~35 inert Linear allows."""
        flat = catalog.get("base_permissions", []) + catalog.get("base_denies", [])
        assert not any("Linear" in rule for rule in flat)

    @pytest.mark.parametrize(
        ("tracker", "marker"),
        [
            (Tracker.LINEAR, "mcp__claude_ai_Linear__get_issue"),
            (Tracker.JIRA, "mcp__claude_ai_Atlassian_Rovo__getJiraIssue"),
            (Tracker.GITHUB, "mcp__plugin_Dev10x_cli__issue_get"),
        ],
    )
    def test_selecting_a_tracker_seeds_its_own_tools(
        self,
        catalog: dict,
        tracker: Tracker,
        marker: str,
    ) -> None:
        merged = apply_tracker_selection(config=catalog, tracker=tracker)
        assert marker in merged["base_permissions"]

    def test_jira_selection_seeds_no_linear_rule(self, catalog: dict) -> None:
        merged = apply_tracker_selection(config=catalog, tracker=Tracker.JIRA)
        seeded = merged["base_permissions"] + merged["base_denies"]
        assert not any("Linear" in rule for rule in seeded)

    def test_linear_selection_still_seeds_its_deletes_as_denies(self, catalog: dict) -> None:
        merged = apply_tracker_selection(config=catalog, tracker=Tracker.LINEAR)
        assert "mcp__claude_ai_Linear__delete_comment" in merged["base_denies"]

    def test_tracker_independent_denies_survive_every_selection(self, catalog: dict) -> None:
        """The privilege-escalation tier is not tracker-specific (GH-326)."""
        for tracker in Tracker:
            merged = apply_tracker_selection(config=catalog, tracker=tracker)
            assert any("sudo" in rule for rule in merged["base_denies"])
