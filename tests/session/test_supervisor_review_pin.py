"""Tests for persisting the project's supervisor-review posture (GH-1165)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.session import supervisor_review_pin


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
    monkeypatch.setattr("dev10x.session.preset_pin._bounded_toplevel", lambda *, cwd=None: None)
    return friction


class TestPinSupervisorReview:
    def test_writes_the_supervisor_review_key(self, repo: Path) -> None:
        result = supervisor_review_pin.pin_supervisor_review(supervisor_review="none")
        assert isinstance(result, SuccessResult)
        assert result.value["prefs"] == {"supervisor_review": "none"}
        doc = yaml.safe_load(repo.read_text())
        assert doc["projects"][0]["supervisor_review"] == "none"

    def test_keys_off_the_repo_stem_so_worktrees_share_it(self, repo: Path) -> None:
        result = supervisor_review_pin.pin_supervisor_review(supervisor_review="required")
        assert isinstance(result, SuccessResult)
        assert result.value["match"] == ["*/acme-repo", "*/acme-repo-*"]

    def test_is_idempotent(self, repo: Path) -> None:
        supervisor_review_pin.pin_supervisor_review(supervisor_review="none")
        supervisor_review_pin.pin_supervisor_review(supervisor_review="none")
        doc = yaml.safe_load(repo.read_text())
        assert len(doc["projects"]) == 1

    def test_repinning_replaces_rather_than_duplicates(self, repo: Path) -> None:
        supervisor_review_pin.pin_supervisor_review(supervisor_review="none")
        supervisor_review_pin.pin_supervisor_review(supervisor_review="required")
        doc = yaml.safe_load(repo.read_text())
        assert len(doc["projects"]) == 1
        assert doc["projects"][0]["supervisor_review"] == "required"

    def test_unknown_value_fails_loud(self, repo: Path) -> None:
        """A typo must not silently coerce to 'required' at gate-resolve time."""
        result = supervisor_review_pin.pin_supervisor_review(supervisor_review="maybe")
        assert isinstance(result, ErrorResult)
        assert "maybe" in result.error

    def test_unknown_scope_fails_loud(self, repo: Path) -> None:
        result = supervisor_review_pin.pin_supervisor_review(
            supervisor_review="none", scope="galaxy"
        )
        assert isinstance(result, ErrorResult)
        assert "galaxy" in result.error

    def test_respects_dir_scope(self, repo: Path) -> None:
        result = supervisor_review_pin.pin_supervisor_review(supervisor_review="none", scope="dir")
        assert isinstance(result, SuccessResult)
        assert result.value["scope"] == "dir"
