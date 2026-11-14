"""`update-paths --global` and `clean --global` reach a tracked user file (GH-1868)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.domain.common.result import ok

from dev10x.commands.permission import clean, update_paths


@pytest.fixture
def claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".claude"
    home.mkdir()
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
    return home


@pytest.fixture
def cache(claude_home: Path) -> Path:
    core = claude_home / "plugins" / "cache" / "Dev10x-Guru" / "dev10x"
    (core / "0.10.0").mkdir(parents=True)
    (core / "0.20.0").mkdir(parents=True)
    return core


@pytest.fixture
def global_settings(claude_home: Path, cache: Path) -> Path:
    path = claude_home / "settings.json"
    path.write_text(json.dumps({"permissions": {"allow": [f"Bash({cache}/0.10.0/foo:*)"]}}))
    return path


@pytest.fixture
def tracked_paths(global_settings: Path) -> set[Path]:
    return {global_settings}


@pytest.fixture
def update_paths_env(
    tmp_path: Path,
    cache: Path,
    global_settings: Path,
    tracked_paths: set[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "projects.yaml"
    config_path.write_text(
        f"plugin_cache: {cache}\nroots: []\ninclude_user_settings: true\nbase_permissions: []\n"
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.update_paths.find_config", lambda: ok(config_path)
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.update_paths.detect_latest_version", lambda _cache: "0.20.0"
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.update_paths.find_settings_files",
        lambda **_kw: [global_settings],
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.catalog_write._is_git_tracked",
        lambda path: path in tracked_paths,
    )


@pytest.fixture
def update_paths_args() -> list[str]:
    return []


@pytest.fixture
def update_paths_run(update_paths_env: None, update_paths_args: list[str]) -> Result:
    return CliRunner().invoke(update_paths, update_paths_args)


class TestUpdatePathsWithoutGlobal:
    def test_skips_the_tracked_user_file(
        self,
        update_paths_run: Result,
        global_settings: Path,
        cache: Path,
    ) -> None:
        assert f"SKIP (git-tracked): {global_settings}" in update_paths_run.output
        allow = json.loads(global_settings.read_text())["permissions"]["allow"]
        assert allow == [f"Bash({cache}/0.10.0/foo:*)"]


class TestUpdatePathsWithGlobal:
    @pytest.fixture
    def update_paths_args(self) -> list[str]:
        return ["--global"]

    def test_rewrites_the_tracked_user_file(
        self,
        update_paths_run: Result,
        global_settings: Path,
        cache: Path,
    ) -> None:
        assert update_paths_run.exit_code == 0, update_paths_run.output
        allow = json.loads(global_settings.read_text())["permissions"]["allow"]
        assert allow == [f"Bash({cache}/0.20.0/foo:*)"]


@pytest.fixture
def global_clean_rules() -> list[str]:
    return ["Bash(git log:*)", "Bash(done)"]


@pytest.fixture
def clean_env(
    tmp_path: Path,
    claude_home: Path,
    global_clean_rules: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    global_file = claude_home / "settings.json"
    global_file.write_text(json.dumps({"permissions": {"allow": global_clean_rules}}))
    config_path = tmp_path / "projects.yaml"
    config_path.write_text(f"plugin_cache: {claude_home}/plugins/cache/x/y\nroots: []\n")
    monkeypatch.setattr(
        "dev10x.skills.permission.clean_project_files.find_config", lambda: ok(config_path)
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.clean_project_files.GLOBAL_SETTINGS", global_file
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.clean_project_files.find_settings_files", lambda **_kw: []
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.clean_project_files.detect_current_version",
        lambda _cache: None,
    )
    return global_file


class TestCleanWithoutGlobal:
    def test_leaves_stale_user_rules_in_place(
        self,
        clean_env: Path,
        global_clean_rules: list[str],
    ) -> None:
        result = CliRunner().invoke(clean, [])

        assert result.exit_code == 0, result.output
        assert json.loads(clean_env.read_text())["permissions"]["allow"] == global_clean_rules


class TestCleanWithGlobal:
    def test_removes_stale_rules_but_never_dedups_the_file_against_itself(
        self,
        clean_env: Path,
    ) -> None:
        result = CliRunner().invoke(clean, ["--global", "--aggressive"])

        assert result.exit_code == 0, result.output
        assert json.loads(clean_env.read_text())["permissions"]["allow"] == ["Bash(git log:*)"]

    def test_counts_the_user_file_once(self, clean_env: Path) -> None:
        result = CliRunner().invoke(clean, ["--global", "--dry-run"])

        assert "Scanning 1 files" in result.output


class TestCleanWithGlobalAndNoUserFile:
    @pytest.fixture
    def missing_global(self, clean_env: Path) -> Path:
        clean_env.unlink()
        return clean_env

    def test_reports_nothing_to_scan(self, missing_global: Path) -> None:
        result = CliRunner().invoke(clean, ["--global"])

        assert result.exit_code == 0, result.output
        assert "No project settings files found." in result.output
