"""`permission clean` leaves git-tracked settings files alone (GH-1983)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from dev10x.commands.permission import clean
from dev10x.core.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.core.domain.common.result import ok

STALE_RULES = ["Bash(git log:*)", "Bash(done)"]


def _write_settings(*, path: Path) -> Path:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"permissions": {"allow": STALE_RULES}}))
    return path


@pytest.fixture
def claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home" / ".claude"
    home.mkdir(parents=True)
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
    return home


@pytest.fixture
def tracked_file(tmp_path: Path) -> Path:
    return _write_settings(path=tmp_path / "tracked" / ".claude" / "settings.local.json")


@pytest.fixture
def untracked_file(tmp_path: Path) -> Path:
    return _write_settings(path=tmp_path / "untracked" / ".claude" / "settings.local.json")


@pytest.fixture
def clean_env(
    tmp_path: Path,
    claude_home: Path,
    tracked_file: Path,
    untracked_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "projects.yaml"
    config_path.write_text(f"plugin_cache: {claude_home}/plugins/cache/x/y\nroots: []\n")
    module = "dev10x.core.skills.permission.clean_project_files"
    monkeypatch.setattr(f"{module}.find_config", lambda: ok(config_path))
    monkeypatch.setattr(f"{module}.GLOBAL_SETTINGS", claude_home / "settings.json")
    monkeypatch.setattr(
        f"{module}.find_settings_files", lambda **_kw: [tracked_file, untracked_file]
    )
    monkeypatch.setattr(f"{module}.detect_current_version", lambda _cache: None)
    monkeypatch.setattr(
        "dev10x.core.skills.permission.catalog_write._is_git_tracked",
        lambda path: path == tracked_file,
    )


@pytest.fixture
def clean_args() -> list[str]:
    return []


@pytest.fixture
def clean_run(clean_env: None, clean_args: list[str]) -> Result:
    return CliRunner().invoke(clean, clean_args)


def _allow(*, path: Path) -> list[str]:
    return json.loads(path.read_text())["permissions"]["allow"]


def _backups(*, path: Path) -> list[Path]:
    return list(path.parent.glob(f"{path.name}.bak.*"))


class TestCleanSkipsTrackedFile:
    def test_prints_skip_line(self, clean_run: Result, tracked_file: Path) -> None:
        assert f"SKIP (git-tracked): {tracked_file}" in clean_run.output

    def test_removes_no_rules(self, clean_run: Result, tracked_file: Path) -> None:
        assert _allow(path=tracked_file) == STALE_RULES

    def test_writes_no_backup(self, clean_run: Result, tracked_file: Path) -> None:
        assert _backups(path=tracked_file) == []


class TestCleanStillCleansUntrackedFile:
    def test_removes_stale_rule(self, clean_run: Result, untracked_file: Path) -> None:
        assert _allow(path=untracked_file) == ["Bash(git log:*)"]

    def test_does_not_skip_it(self, clean_run: Result, untracked_file: Path) -> None:
        assert f"SKIP (git-tracked): {untracked_file}" not in clean_run.output


class TestCleanDryRunSkipsTrackedFile:
    @pytest.fixture
    def clean_args(self) -> list[str]:
        return ["--dry-run"]

    def test_prints_skip_line(self, clean_run: Result, tracked_file: Path) -> None:
        assert f"SKIP (git-tracked): {tracked_file}" in clean_run.output

    def test_reports_only_untracked_file(
        self,
        clean_run: Result,
        tracked_file: Path,
        untracked_file: Path,
    ) -> None:
        assert f"\n{untracked_file}" in clean_run.output
        assert f"\n{tracked_file}" not in clean_run.output

    def test_modifies_nothing(
        self,
        clean_run: Result,
        tracked_file: Path,
        untracked_file: Path,
    ) -> None:
        assert _allow(path=tracked_file) == STALE_RULES
        assert _allow(path=untracked_file) == STALE_RULES
