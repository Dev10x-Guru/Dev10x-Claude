"""Tests for `dev10x session reap` (GH-1253).

The maintenance machinery's only removal path. Everything else ensures
something is present, so a pin for an ephemeral worktree outlives the
worktree indefinitely — and first-match-wins evaluation walks every dead
one before reaching a real project.

The config home is isolated to a tmp dir by the autouse conftest
fixture, so these never touch the developer's real friction.yaml.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from dev10x.commands.session import session
from dev10x.domain.dev10x_paths import Dev10xConfigDir


def _seed(projects: list[dict]) -> Path:
    path = Dev10xConfigDir.friction_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"defaults": {"active_modes": []}, "projects": projects}),
        encoding="utf-8",
    )
    return path


def _projects(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["projects"]


class TestReap:
    def test_it_removes_a_pin_whose_worktree_is_gone(self, tmp_path: Path) -> None:
        path = _seed(
            [
                {"match": ["*/agent-dead", str(tmp_path / "gone")], "gate_overlays": ["afk"]},
                {"match": ["*/tt-pos"], "supervisor_review": "required"},
            ]
        )

        result = CliRunner().invoke(session, ["reap"])

        assert result.exit_code == 0
        assert len(_projects(path)) == 1

    def test_it_reports_what_changed(self, tmp_path: Path) -> None:
        _seed([{"match": [str(tmp_path / "gone")]}])

        result = CliRunner().invoke(session, ["reap"])

        assert "1 → 0" in result.output

    def test_a_clean_config_is_left_alone(self) -> None:
        path = _seed([{"match": ["*/tt-pos"]}])
        before = path.read_text(encoding="utf-8")

        result = CliRunner().invoke(session, ["reap"])

        assert "0 provably dead" in result.output
        assert path.read_text(encoding="utf-8") == before


class TestDryRun:
    def test_it_writes_nothing(self, tmp_path: Path) -> None:
        path = _seed([{"match": [str(tmp_path / "gone")]}])
        before = path.read_text(encoding="utf-8")

        result = CliRunner().invoke(session, ["reap", "--dry-run"])

        assert result.exit_code == 0
        assert path.read_text(encoding="utf-8") == before

    def test_it_names_the_entries_it_would_remove(self, tmp_path: Path) -> None:
        _seed([{"match": ["*/agent-dead", str(tmp_path / "gone")]}, {"match": ["*/live"]}])

        result = CliRunner().invoke(session, ["reap", "--dry-run"])

        assert "1 provably dead" in result.output
        assert "*/agent-dead" in result.output

    def test_a_live_entry_is_not_listed(self, tmp_path: Path) -> None:
        _seed([{"match": ["*/live", str(tmp_path)]}])

        result = CliRunner().invoke(session, ["reap", "--dry-run"])

        assert "0 provably dead" in result.output
