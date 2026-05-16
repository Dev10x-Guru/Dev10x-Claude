"""Tests for uv-run-project pattern detection (GH-137)."""

from __future__ import annotations

import pytest

mod = pytest.importorskip(
    "dev10x.skills.permission.uv_run_project",
    reason="dev10x not installed",
)


class TestDetect:
    def test_finds_basic_project_flag(self) -> None:
        matches = mod.detect(
            commands=["uv run --project apps/api pre-commit run --files src/a.py"],
        )
        assert len(matches) == 1
        assert matches[0].project_path == "apps/api"
        assert matches[0].tool == "pre-commit"

    def test_finds_pytest_under_project(self) -> None:
        matches = mod.detect(
            commands=["uv run --project apps/web pytest tests/"],
        )
        assert len(matches) == 1
        assert matches[0].project_path == "apps/web"
        assert matches[0].tool == "pytest"

    def test_handles_extra_flag_combo(self) -> None:
        matches = mod.detect(
            commands=["uv run --project apps/api --extra dev pytest tests/"],
        )
        assert len(matches) == 1
        assert matches[0].project_path == "apps/api"

    def test_ignores_plain_uv_run(self) -> None:
        matches = mod.detect(commands=["uv run pytest tests/"])
        assert matches == []

    def test_ignores_unrelated_commands(self) -> None:
        matches = mod.detect(
            commands=["git status", "gh pr view 42", "find /tmp -name x"],
        )
        assert matches == []


class TestProposeRules:
    def test_collapses_multiple_tools_per_project(self) -> None:
        matches = [
            mod.UvRunProjectMatch(
                command="uv run --project apps/api pytest",
                project_path="apps/api",
                tool="pytest",
            ),
            mod.UvRunProjectMatch(
                command="uv run --project apps/api ruff check",
                project_path="apps/api",
                tool="ruff",
            ),
            mod.UvRunProjectMatch(
                command="uv run --project apps/api mypy .",
                project_path="apps/api",
                tool="mypy",
            ),
        ]

        proposals = mod.propose_rules(matches=matches)

        assert len(proposals) == 1
        assert proposals[0].rule == "Bash(uv run --project apps/api:*)"
        assert sorted(proposals[0].tools_seen) == ["mypy", "pytest", "ruff"]

    def test_separates_distinct_projects(self) -> None:
        matches = [
            mod.UvRunProjectMatch(
                command="uv run --project apps/api pytest",
                project_path="apps/api",
                tool="pytest",
            ),
            mod.UvRunProjectMatch(
                command="uv run --project apps/web pytest",
                project_path="apps/web",
                tool="pytest",
            ),
        ]
        proposals = mod.propose_rules(matches=matches)
        assert len(proposals) == 2
        assert proposals[0].project_path == "apps/api"
        assert proposals[1].project_path == "apps/web"
