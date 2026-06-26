"""Tests for `dev10x session seed` (GH-705)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.session import session


def _seed_path(root: Path) -> Path:
    return root / ".claude" / "Dev10x" / "session.yaml"


class TestSeedWhenAbsent:
    @pytest.fixture
    def result(self, tmp_path: Path) -> object:
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_creates_session_yaml(self, result: object, tmp_path: Path) -> None:
        assert _seed_path(tmp_path).exists()

    def test_defaults_to_guided(self, result: object, tmp_path: Path) -> None:
        assert "friction_level: guided" in _seed_path(tmp_path).read_text()

    def test_reports_seeded(self, result: object) -> None:
        assert "seeded" in result.output


class TestSeedIsIdempotent:
    @pytest.fixture
    def existing(self, tmp_path: Path) -> Path:
        target = _seed_path(tmp_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("friction_level: adaptive\nactive_modes: ['solo-maintainer']\n")
        return target

    @pytest.fixture
    def result(self, existing: Path, tmp_path: Path) -> object:
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_preserves_existing_content(self, result: object, existing: Path) -> None:
        assert existing.read_text() == (
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

    def test_seeds_requested_level(self, result: object, tmp_path: Path) -> None:
        assert "friction_level: adaptive" in _seed_path(tmp_path).read_text()
