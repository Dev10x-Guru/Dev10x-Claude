"""Tests for `dev10x session seed` (ADR-0018 relocation).

Seed no longer writes a per-repo ``config.yaml``/``session.yaml`` — durable
prefs live in the global ``~/.config/Dev10x/friction.yaml`` (isolated to a
tmp home by the conftest fixture). Seed only ensures that global file exists
and drops a self-ignoring ``.claude/Dev10x/.gitignore`` for the MCP-written
auto-advance doubt-sink.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.session import session
from dev10x.domain.dev10x_paths import Dev10xConfigDir


def _gitignore_path(root: Path) -> Path:
    return root / ".claude" / "Dev10x" / ".gitignore"


def _dev10x_dir(root: Path) -> Path:
    return root / ".claude" / "Dev10x"


class TestSeedGitignore:
    """GH-809: seed a self-ignoring .claude/Dev10x/.gitignore ("*")."""

    def test_creates_gitignore_with_star(self, tmp_path: Path) -> None:
        CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])
        assert _gitignore_path(tmp_path).read_text() == "*\n"

    def test_idempotent_preserves_existing_gitignore(self, tmp_path: Path) -> None:
        existing = _gitignore_path(tmp_path)
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("# custom\n")
        CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])
        assert existing.read_text() == "# custom\n"

    def test_reports_seeded_gitignore(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])
        assert ".gitignore" in result.output


class TestSeedFrictionYaml:
    """ADR-0018: seed ensures the global friction.yaml (starter defaults)."""

    @pytest.fixture
    def result(self, tmp_path: Path) -> object:
        return CliRunner().invoke(session, ["seed", "--path", str(tmp_path)])

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_creates_global_friction_yaml(self, result: object) -> None:
        assert Dev10xConfigDir.friction_yaml().exists()

    def test_defaults_to_guided(self, result: object) -> None:
        assert "friction_level: guided" in Dev10xConfigDir.friction_yaml().read_text()

    def test_writes_nothing_durable_under_repo_claude(
        self, result: object, tmp_path: Path
    ) -> None:
        assert not (_dev10x_dir(tmp_path) / "config.yaml").exists()
        assert not (_dev10x_dir(tmp_path) / "session.yaml").exists()

    def test_reports_seeded(self, result: object) -> None:
        assert "seeded" in result.output


class TestSeedFrictionLevel:
    def test_seeds_requested_level(self, tmp_path: Path) -> None:
        CliRunner().invoke(
            session, ["seed", "--path", str(tmp_path), "--friction-level", "adaptive"]
        )
        assert "friction_level: adaptive" in Dev10xConfigDir.friction_yaml().read_text()


class TestSeedIsIdempotent:
    def test_preserves_existing_friction_yaml(self, tmp_path: Path) -> None:
        friction = Dev10xConfigDir.friction_yaml()
        friction.parent.mkdir(parents=True, exist_ok=True)
        friction.write_text("defaults:\n  friction_level: strict\n")
        result = CliRunner().invoke(
            session, ["seed", "--path", str(tmp_path), "--friction-level", "adaptive"]
        )
        # A present global file is preserved; the requested level is ignored.
        assert friction.read_text() == "defaults:\n  friction_level: strict\n"
        assert "already present" in result.output
