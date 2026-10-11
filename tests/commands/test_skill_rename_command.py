"""`dev10x skill rename` CLI (ADR-0034 Stage A4, GH-1558)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from dev10x.cli import cli

SKILL_TEXT = "---\nname: dev10x:gog\n---\nSkill(dev10x:gog)\n"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "skills" / "gog").mkdir(parents=True)
    (tmp_path / "skills" / "gog" / "SKILL.md").write_text(SKILL_TEXT)
    return tmp_path


@pytest.fixture
def dry_run(tree: Path) -> Result:
    return CliRunner().invoke(
        cli, ["skill", "rename", "dev10x:gog", "dev10x-comm:gog", "--root", str(tree)]
    )


@pytest.fixture
def applied(tree: Path) -> Result:
    return CliRunner().invoke(
        cli,
        ["skill", "rename", "gog", "dev10x-comm:gog", "--root", str(tree), "--apply"],
    )


class TestDryRun:
    def test_exits_zero(self, dry_run: Result) -> None:
        assert dry_run.exit_code == 0

    def test_prints_the_diff(self, dry_run: Result) -> None:
        assert "-name: dev10x:gog\n+name: dev10x-comm:gog\n" in dry_run.output

    def test_says_nothing_was_written(self, dry_run: Result) -> None:
        assert (
            "Dry run, nothing written. Would rewrite 2 reference(s) in 1 file(s): "
            "dev10x:gog -> dev10x-comm:gog. Pass --apply to write." in dry_run.output
        )

    def test_leaves_the_file_alone(self, tree: Path, dry_run: Result) -> None:
        assert (tree / "skills" / "gog" / "SKILL.md").read_text() == SKILL_TEXT


class TestApply:
    def test_reports_the_rewrite(self, applied: Result) -> None:
        assert "Rewrote 2 reference(s) in 1 file(s)" in applied.output

    def test_writes_the_file(self, tree: Path, applied: Result) -> None:
        assert (tree / "skills" / "gog" / "SKILL.md").read_text() == (
            "---\nname: dev10x-comm:gog\n---\nSkill(dev10x-comm:gog)\n"
        )


class TestErrors:
    def test_unknown_plugin_exits_one(self, tree: Path) -> None:
        result = CliRunner().invoke(
            cli, ["skill", "rename", "gog", "nowhere:gog", "--root", str(tree)]
        )

        assert (result.exit_code, "unknown plugin 'nowhere'" in result.output) == (1, True)
