"""Tests for persisting the project's tracker choice (GH-768)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.session import tracker_pin


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A resolvable repo identity plus an isolated friction.yaml."""
    root = tmp_path / "acme-repo"
    root.mkdir()
    friction = tmp_path / "friction.yaml"
    monkeypatch.setattr(
        "dev10x.domain.documents.session_yaml.Dev10xConfigDir.friction_yaml",
        classmethod(lambda cls: friction),
    )
    monkeypatch.setattr(
        "dev10x.session.preset_pin.resolve_repo_identity",
        lambda *, cwd=None: SuccessResult(
            value={"name": "acme-repo", "root": str(root), "source": "test"}
        ),
    )
    monkeypatch.setattr(
        "dev10x.session.tracker_pin.resolve_repo_identity",
        lambda *, cwd=None: SuccessResult(
            value={"name": "acme-repo", "root": str(root), "source": "test"}
        ),
    )
    monkeypatch.setattr("dev10x.session.preset_pin._bounded_toplevel", lambda *, cwd=None: None)
    return friction


class TestPinTracker:
    def test_writes_the_tracker_key(self, repo: Path) -> None:
        result = tracker_pin.pin_tracker(tracker="jira")
        assert isinstance(result, SuccessResult)
        assert result.value["prefs"] == {"tracker": "jira"}
        doc = yaml.safe_load(repo.read_text())
        assert doc["projects"][0]["tracker"] == "jira"

    def test_keys_off_the_repo_stem_so_worktrees_share_it(self, repo: Path) -> None:
        result = tracker_pin.pin_tracker(tracker="github")
        assert isinstance(result, SuccessResult)
        assert result.value["match"] == ["*/acme-repo", "*/acme-repo-*"]

    def test_is_idempotent(self, repo: Path) -> None:
        tracker_pin.pin_tracker(tracker="jira")
        tracker_pin.pin_tracker(tracker="jira")
        doc = yaml.safe_load(repo.read_text())
        assert len(doc["projects"]) == 1

    def test_repinning_replaces_rather_than_duplicates(self, repo: Path) -> None:
        tracker_pin.pin_tracker(tracker="jira")
        tracker_pin.pin_tracker(tracker="github")
        doc = yaml.safe_load(repo.read_text())
        assert len(doc["projects"]) == 1
        assert doc["projects"][0]["tracker"] == "github"

    def test_normalizes_case(self, repo: Path) -> None:
        result = tracker_pin.pin_tracker(tracker="JIRA")
        assert isinstance(result, SuccessResult)
        assert result.value["prefs"]["tracker"] == "jira"

    def test_unknown_tracker_fails_loud(self, repo: Path) -> None:
        """A typo must not silently degrade to the default at seeding time."""
        result = tracker_pin.pin_tracker(tracker="gitlab")
        assert isinstance(result, ErrorResult)
        assert "gitlab" in result.error

    def test_unknown_scope_fails_loud(self, repo: Path) -> None:
        result = tracker_pin.pin_tracker(tracker="jira", scope="galaxy")
        assert isinstance(result, ErrorResult)
        assert "galaxy" in result.error


class TestTrackerStatus:
    def test_unpinned_repo_reports_the_default(self, repo: Path) -> None:
        result = tracker_pin.tracker_status()
        assert isinstance(result, SuccessResult)
        assert result.value["pinned"] is False
        assert result.value["tracker"] == "linear"
        assert result.value["source"] == "default"

    def test_pinned_repo_reports_its_choice(self, repo: Path) -> None:
        tracker_pin.pin_tracker(tracker="jira")
        result = tracker_pin.tracker_status()
        assert isinstance(result, SuccessResult)
        assert result.value["pinned"] is True
        assert result.value["tracker"] == "jira"
        assert result.value["source"] == "project"

    def test_defaults_block_is_reported_as_unpinned(self, repo: Path) -> None:
        """`pinned` gates the onboarding ask — a global default is not an answer."""
        repo.write_text(yaml.safe_dump({"defaults": {"tracker": "github"}}), encoding="utf-8")
        result = tracker_pin.tracker_status()
        assert isinstance(result, SuccessResult)
        assert result.value["pinned"] is False
        assert result.value["tracker"] == "github"
        assert result.value["source"] == "defaults"

    def test_reports_the_offerable_choices(self, repo: Path) -> None:
        result = tracker_pin.tracker_status()
        assert isinstance(result, SuccessResult)
        assert result.value["choices"] == ["linear", "jira", "github"]

    def test_unresolvable_repo_is_an_error(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "dev10x.session.tracker_pin.resolve_repo_identity",
            lambda *, cwd=None: ErrorResult(error="Not in a git repository"),
        )
        assert isinstance(tracker_pin.tracker_status(), ErrorResult)
