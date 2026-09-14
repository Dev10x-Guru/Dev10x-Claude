"""Tests for persisting the project's IDE choice (GH-1261)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.session import ide_pin


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
    for module in ("dev10x.session.preset_pin", "dev10x.session.ide_pin"):
        monkeypatch.setattr(
            f"{module}.resolve_repo_identity",
            lambda *, cwd=None: SuccessResult(
                value={"name": "acme-repo", "root": str(root), "source": "test"}
            ),
        )
    monkeypatch.setattr("dev10x.session.preset_pin._bounded_toplevel", lambda *, cwd=None: None)
    return friction


class TestPinIde:
    def test_writes_the_ide_key(self, repo: Path) -> None:
        result = ide_pin.pin_ide(ide="pycharm")
        assert isinstance(result, SuccessResult)
        assert result.value["prefs"] == {"ide": "pycharm"}
        doc = yaml.safe_load(repo.read_text())
        assert doc["projects"][0]["ide"] == "pycharm"

    def test_keys_off_the_repo_stem_so_worktrees_share_it(self, repo: Path) -> None:
        result = ide_pin.pin_ide(ide="pycharm")
        assert isinstance(result, SuccessResult)
        assert result.value["match"] == ["*/acme-repo", "*/acme-repo-*"]

    def test_repinning_replaces_rather_than_duplicates(self, repo: Path) -> None:
        ide_pin.pin_ide(ide="pycharm")
        ide_pin.pin_ide(ide="none")
        doc = yaml.safe_load(repo.read_text())
        assert len(doc["projects"]) == 1
        assert doc["projects"][0]["ide"] == "none"

    def test_none_is_a_pinnable_answer(self, repo: Path) -> None:
        # "I run no IDE server" must be recordable, or the gate re-asks
        # forever the one setup that has nothing to seed.
        ide_pin.pin_ide(ide="none")
        result = ide_pin.ide_status()
        assert isinstance(result, SuccessResult)
        assert result.value["pinned"] is True
        assert result.value["ide"] == "none"

    def test_normalizes_case(self, repo: Path) -> None:
        result = ide_pin.pin_ide(ide="PyCharm")
        assert isinstance(result, SuccessResult)
        assert result.value["prefs"]["ide"] == "pycharm"

    def test_unknown_ide_fails_loud(self, repo: Path) -> None:
        """A typo must not degrade to `none` — that seeds nothing, silently."""
        result = ide_pin.pin_ide(ide="vscode")
        assert isinstance(result, ErrorResult)
        assert "vscode" in result.error

    def test_unknown_scope_fails_loud(self, repo: Path) -> None:
        result = ide_pin.pin_ide(ide="pycharm", scope="galaxy")
        assert isinstance(result, ErrorResult)
        assert "galaxy" in result.error


class TestIdeStatus:
    def test_unpinned_repo_resolves_to_none(self, repo: Path) -> None:
        result = ide_pin.ide_status()
        assert isinstance(result, SuccessResult)
        assert result.value["pinned"] is False
        assert result.value["ide"] == "none"
        assert result.value["source"] == "default"

    def test_pinned_repo_reports_its_choice(self, repo: Path) -> None:
        ide_pin.pin_ide(ide="pycharm")
        result = ide_pin.ide_status()
        assert isinstance(result, SuccessResult)
        assert result.value["pinned"] is True
        assert result.value["ide"] == "pycharm"
        assert result.value["source"] == "project"

    def test_defaults_block_is_reported_as_unpinned(self, repo: Path) -> None:
        """`pinned` gates the onboarding ask — a global default is not an answer."""
        repo.write_text(yaml.safe_dump({"defaults": {"ide": "pycharm"}}), encoding="utf-8")
        result = ide_pin.ide_status()
        assert isinstance(result, SuccessResult)
        assert result.value["pinned"] is False
        assert result.value["ide"] == "pycharm"
        assert result.value["source"] == "defaults"

    def test_reports_the_offerable_choices(self, repo: Path) -> None:
        result = ide_pin.ide_status()
        assert isinstance(result, SuccessResult)
        assert result.value["choices"] == ["pycharm", "none"]

    def test_unresolvable_repo_is_an_error(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "dev10x.session.ide_pin.resolve_repo_identity",
            lambda *, cwd=None: ErrorResult(error="Not in a git repository"),
        )
        assert isinstance(ide_pin.ide_status(), ErrorResult)
