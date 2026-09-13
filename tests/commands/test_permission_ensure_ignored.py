"""Tests for `dev10x permission ensure-ignored` (GH-1275).

This command is the whole point of the module behind it. The ignore rule
shipped once with a correct implementation and no caller anywhere in the
tree, so the reported symptom — an untracked `.claude/Dev10x/` in every
worktree — stayed unfixed while every unit test passed. These tests
exercise the route a maintenance pass actually takes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.permission import ensure_ignored as ensure_ignored_cmd
from dev10x.domain.common.result import ok
from dev10x.permission.service import PermissionContext

_TIMEOUT_SECONDS = 30


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrub the developer's git config for the CODE under test too.

    The command reaches git through `subprocess_utils.run`, which forwards
    no `env`, so this must go on `os.environ` — an `env=` argument would
    scrub only this file's own git calls and leave the command reading a
    global `core.excludesFile` that may already cover `.claude/`.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(root)],
        check=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return root


def _with_roots(monkeypatch: pytest.MonkeyPatch, roots: list[str]) -> None:
    import dev10x.commands.permission as cmd

    context = PermissionContext(
        config_path=Path("/config.yaml"),
        config={"roots": roots},
        settings_files=[],
    )
    monkeypatch.setattr(cmd, "load_permission_context", lambda **_kw: ok(context))


def _exclude(repo_root: Path) -> str:
    path = repo_root / ".git" / "info" / "exclude"
    return path.read_text(encoding="utf-8") if path.exists() else ""


class TestTheCommandReachesTheModule:
    def test_it_writes_the_rule_for_a_configured_root(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_roots(monkeypatch, [str(repo)])

        result = CliRunner().invoke(ensure_ignored_cmd, [])

        assert result.exit_code == 0
        assert ".claude/Dev10x/" in _exclude(repo)

    def test_it_reports_what_it_did(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_roots(monkeypatch, [str(repo)])

        result = CliRunner().invoke(ensure_ignored_cmd, [])

        assert "1 of 1 repo(s) gained the rule." in result.output

    def test_a_second_run_changes_nothing(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_roots(monkeypatch, [str(repo)])
        CliRunner().invoke(ensure_ignored_cmd, [])
        after_first = _exclude(repo)

        result = CliRunner().invoke(ensure_ignored_cmd, [])

        assert _exclude(repo) == after_first
        assert "0 of 1 repo(s) gained the rule." in result.output

    def test_it_visits_every_configured_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        roots = []
        for name in ("alpha", "beta"):
            root = tmp_path / name
            root.mkdir()
            subprocess.run(
                ["git", "init", "-q", "-b", "main", str(root)],
                check=True,
                timeout=_TIMEOUT_SECONDS,
            )
            roots.append(root)
        _with_roots(monkeypatch, [str(root) for root in roots])

        CliRunner().invoke(ensure_ignored_cmd, [])

        assert [".claude/Dev10x/" in _exclude(root) for root in roots] == [True, True]


class TestDryRun:
    def test_it_writes_nothing(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_roots(monkeypatch, [str(repo)])
        before = _exclude(repo)

        result = CliRunner().invoke(ensure_ignored_cmd, ["--dry-run"])

        assert result.exit_code == 0
        assert _exclude(repo) == before

    def test_it_says_what_would_change(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_roots(monkeypatch, [str(repo)])

        result = CliRunner().invoke(ensure_ignored_cmd, ["--dry-run"])

        assert "1 of 1 repo(s) would gain the rule." in result.output


class TestReporting:
    def test_it_offers_the_tracked_spelling(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_roots(monkeypatch, [str(repo)])

        result = CliRunner().invoke(ensure_ignored_cmd, [])

        assert "/Dev10x/" in result.output

    def test_quiet_drops_the_per_repo_lines(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_roots(monkeypatch, [str(repo)])

        result = CliRunner().invoke(ensure_ignored_cmd, ["--quiet"])

        assert str(repo) not in result.output.split("Optional")[0]

    def test_a_non_repository_root_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        _with_roots(monkeypatch, [str(plain)])

        result = CliRunner().invoke(ensure_ignored_cmd, [])

        assert result.exit_code == 0
        assert "not a git repository" in result.output

    def test_no_roots_is_reported_not_crashed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_roots(monkeypatch, [])

        result = CliRunner().invoke(ensure_ignored_cmd, [])

        assert result.exit_code == 0
        assert "No roots configured" in result.output
