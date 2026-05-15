"""Tests for `dev10x permission investigate` subcommands (GH-79 #G4).

Covers all six subcommands: prepare, apply, record, restore, report, delta.
Uses Click's CliRunner. Each test redirects the investigator workdir to a
tmp_path-based location so fixtures and matrix state stay isolated.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dev10x.commands.permission import permission


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    return home


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "investigator"


@pytest.fixture
def patched_workdir(workdir: Path, fake_home: Path):
    """Redirect default workdir + Path.home() so commands operate in tmp_path."""

    def _workdir() -> Path:
        return workdir

    with (
        patch("dev10x.commands.permission._investigator_workdir", _workdir),
        patch("dev10x.commands.permission.Path.home", return_value=fake_home),
    ):
        yield workdir


def _state(*, workdir: Path) -> dict:
    return json.loads((workdir / "matrix.json").read_text())


class TestInvestigatePrepare:
    def test_creates_workdir_and_matrix_state(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        result = runner.invoke(permission, ["investigate", "prepare"])

        assert result.exit_code == 0, result.output
        assert (patched_workdir / "matrix.json").is_file()

    def test_state_contains_cells_and_fixture_metadata(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])

        state = _state(workdir=patched_workdir)

        assert "cells" in state
        assert len(state["cells"]) > 0
        assert "fixture" in state
        assert "project_settings" in state["fixture"]
        assert "global_settings" in state["fixture"]

    def test_echoes_workdir_and_cell_count(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        result = runner.invoke(permission, ["investigate", "prepare"])

        assert "Workdir:" in result.output
        assert "Cells:" in result.output

    def test_explicit_workdir_option_writes_redirect_in_default(
        self,
        runner: CliRunner,
        tmp_path: Path,
        fake_home: Path,
    ) -> None:
        custom = tmp_path / "custom-workdir"
        default_workdir = tmp_path / "default-workdir"

        with (
            patch(
                "dev10x.commands.permission._investigator_workdir",
                lambda: default_workdir,
            ),
            patch("dev10x.commands.permission.Path.home", return_value=fake_home),
        ):
            result = runner.invoke(
                permission,
                ["investigate", "prepare", "--workdir", str(custom)],
            )

        assert result.exit_code == 0, result.output
        assert (custom / "matrix.json").is_file()
        redirect = json.loads((default_workdir / "matrix.json").read_text())
        assert redirect["redirect"] == str(custom / "matrix.json")


class TestInvestigateApply:
    def test_errors_when_state_missing(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        result = runner.invoke(permission, ["investigate", "apply", "any-cell"])

        assert result.exit_code == 1
        assert "state missing" in result.output

    def test_errors_when_cell_id_unknown(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])

        result = runner.invoke(permission, ["investigate", "apply", "no-such-cell"])

        assert result.exit_code == 1
        assert "unknown cell_id" in result.output

    def test_applies_rule_for_known_cell(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])
        state = _state(workdir=patched_workdir)
        cell_id = state["cells"][0]["cell_id"]

        result = runner.invoke(permission, ["investigate", "apply", cell_id])

        assert result.exit_code == 0, result.output
        assert "Applied rule:" in result.output
        assert "Targets:" in result.output


class TestInvestigateRecord:
    def test_errors_when_state_missing(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        result = runner.invoke(permission, ["investigate", "record", "any-cell"])

        assert result.exit_code == 1
        assert "state missing" in result.output

    def test_records_auto_approved_outcome(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])
        state = _state(workdir=patched_workdir)
        cell_id = state["cells"][0]["cell_id"]

        result = runner.invoke(
            permission,
            [
                "investigate",
                "record",
                cell_id,
                "--auto-approved",
                "--notes",
                "worked on first try",
            ],
        )

        assert result.exit_code == 0, result.output
        recorded = _state(workdir=patched_workdir)["results"][cell_id]
        assert recorded["auto_approved"] is True
        assert recorded["prompted"] is False
        assert recorded["notes"] == "worked on first try"

    def test_records_prompted_outcome_with_error(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])
        state = _state(workdir=patched_workdir)
        cell_id = state["cells"][0]["cell_id"]

        runner.invoke(
            permission,
            [
                "investigate",
                "record",
                cell_id,
                "--prompted",
                "--error",
                "tool denied",
            ],
        )

        recorded = _state(workdir=patched_workdir)["results"][cell_id]
        assert recorded["auto_approved"] is False
        assert recorded["prompted"] is True
        assert recorded["error"] == "tool denied"


class TestInvestigateRestore:
    def test_noop_when_state_missing(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        result = runner.invoke(permission, ["investigate", "restore"])

        assert result.exit_code == 0
        assert "Nothing to restore" in result.output

    def test_restores_snapshots_and_removes_publisher_root(
        self,
        runner: CliRunner,
        patched_workdir: Path,
        fake_home: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])
        state = _state(workdir=patched_workdir)
        publisher_root = Path(state["fixture"]["publisher_root"])
        project_settings = Path(state["fixture"]["project_settings"])
        # Mutate the project settings so we can verify restore overwrites them
        project_settings.write_text('{"permissions": {"allow": ["sentinel"]}}')

        result = runner.invoke(permission, ["investigate", "restore"])

        assert result.exit_code == 0, result.output
        assert "Restored" in result.output
        assert not publisher_root.exists()
        restored = json.loads(project_settings.read_text())
        assert "sentinel" not in restored["permissions"]["allow"]


class TestInvestigateReport:
    def test_errors_when_state_missing(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        result = runner.invoke(permission, ["investigate", "report"])

        assert result.exit_code == 1
        assert "state missing" in result.output

    def test_renders_markdown_to_stdout_when_no_output_path(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])

        result = runner.invoke(permission, ["investigate", "report"])

        assert result.exit_code == 0, result.output
        # Markdown report contains some recognisable heading
        assert "#" in result.output

    def test_writes_report_to_output_path(
        self,
        runner: CliRunner,
        patched_workdir: Path,
        tmp_path: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])
        out = tmp_path / "report.md"

        result = runner.invoke(
            permission,
            ["investigate", "report", "--output", str(out)],
        )

        assert result.exit_code == 0, result.output
        assert out.is_file()
        assert out.read_text()  # non-empty
        assert f"Wrote report to {out}" in result.output


class TestInvestigateDelta:
    def test_errors_when_state_missing(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        result = runner.invoke(permission, ["investigate", "delta"])

        assert result.exit_code == 1
        assert "state missing" in result.output

    def test_reports_delta_against_current_base_permissions(
        self,
        runner: CliRunner,
        patched_workdir: Path,
    ) -> None:
        runner.invoke(permission, ["investigate", "prepare"])

        result = runner.invoke(permission, ["investigate", "delta"])

        assert result.exit_code == 0, result.output
        assert "Ineffective rules" in result.output
        assert "Suggested replacements" in result.output
