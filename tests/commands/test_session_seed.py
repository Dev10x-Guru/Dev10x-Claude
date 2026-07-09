"""Tests for `dev10x session seed` (GH-705, GH-774 split)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.session import session


def _session_path(root: Path) -> Path:
    return root / ".claude" / "Dev10x" / "session.yaml"


def _config_path(root: Path) -> Path:
    return root / ".claude" / "Dev10x" / "config.yaml"


def _gitignore_path(root: Path) -> Path:
    return root / ".claude" / "Dev10x" / ".gitignore"


class TestSeedGitignore:
    """GH-809: seed a self-ignoring .claude/Dev10x/.gitignore ("*")."""

    def test_creates_gitignore_with_star(self, tmp_path: Path) -> None:
        CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])
        assert _gitignore_path(tmp_path).read_text() == "*\n"

    def test_created_independently_of_existing_config(self, tmp_path: Path) -> None:
        config = _config_path(tmp_path)
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("friction_level: adaptive\n")
        CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])
        assert _gitignore_path(tmp_path).exists()

    def test_idempotent_preserves_existing_gitignore(self, tmp_path: Path) -> None:
        existing = _gitignore_path(tmp_path)
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("# custom\nsession.yaml\n")
        CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])
        assert existing.read_text() == "# custom\nsession.yaml\n"

    def test_reports_seeded_gitignore(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])
        assert ".gitignore" in result.output


class TestSeedWhenAbsent:
    @pytest.fixture
    def result(self, tmp_path: Path) -> object:
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_creates_config_yaml(self, result: object, tmp_path: Path) -> None:
        assert _config_path(tmp_path).exists()

    def test_creates_session_yaml(self, result: object, tmp_path: Path) -> None:
        assert _session_path(tmp_path).exists()

    def test_config_defaults_to_guided(self, result: object, tmp_path: Path) -> None:
        assert "friction_level: guided" in _config_path(tmp_path).read_text()

    def test_session_stub_has_no_durable_keys(self, result: object, tmp_path: Path) -> None:
        assert "friction_level" not in _session_path(tmp_path).read_text()

    def test_reports_seeded(self, result: object) -> None:
        assert "seeded" in result.output


class TestSeedMigratesPreSplitSession:
    """A pre-split session.yaml's durable prefs migrate into config.yaml."""

    @pytest.fixture
    def result(self, tmp_path: Path) -> object:
        legacy = _session_path(tmp_path)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("friction_level: adaptive\nactive_modes: ['solo-maintainer']\n")
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_migrates_level_into_config(self, result: object, tmp_path: Path) -> None:
        assert "friction_level: adaptive" in _config_path(tmp_path).read_text()

    def test_migrates_modes_into_config(self, result: object, tmp_path: Path) -> None:
        assert "solo-maintainer" in _config_path(tmp_path).read_text()

    def test_preserves_existing_session_yaml(self, result: object, tmp_path: Path) -> None:
        assert _session_path(tmp_path).read_text() == (
            "friction_level: adaptive\nactive_modes: ['solo-maintainer']\n"
        )


class TestSeedCarriesAllowedOverlays:
    """GH-805: a pre-split allowed_overlays migrates into config.yaml so the
    repo-character guard is not silently dropped on migration."""

    @pytest.fixture
    def result(self, tmp_path: Path) -> object:
        legacy = _session_path(tmp_path)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("friction_level: guided\nallowed_overlays: []\n")
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_migrates_allow_list_into_config(self, result: object, tmp_path: Path) -> None:
        assert "allowed_overlays: []" in _config_path(tmp_path).read_text()


class TestSeedOmitsAllowedOverlaysWhenUnset:
    """Back-compat: no allowed_overlays on the source → none in the seed."""

    @pytest.fixture
    def result(self, tmp_path: Path) -> object:
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_config_has_no_allowed_overlays_key(self, result: object, tmp_path: Path) -> None:
        assert "allowed_overlays" not in _config_path(tmp_path).read_text()


class TestSeedIsIdempotent:
    @pytest.fixture
    def existing_config(self, tmp_path: Path) -> Path:
        target = _config_path(tmp_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("friction_level: adaptive\nactive_modes: ['solo-maintainer']\n")
        return target

    @pytest.fixture
    def result(self, existing_config: Path, tmp_path: Path) -> object:
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_preserves_existing_config(self, result: object, existing_config: Path) -> None:
        assert existing_config.read_text() == (
            "friction_level: adaptive\nactive_modes: ['solo-maintainer']\n"
        )

    def test_reports_already_present(self, result: object) -> None:
        assert "already present" in result.output


class TestSeedFrictionLevel:
    @pytest.fixture
    def result(self, tmp_path: Path) -> object:
        return CliRunner().invoke(
            session, ["seed", "--path", str(tmp_path), "--friction-level", "adaptive"]
        )

    def test_seeds_requested_level_into_config(self, result: object, tmp_path: Path) -> None:
        assert "friction_level: adaptive" in _config_path(tmp_path).read_text()
