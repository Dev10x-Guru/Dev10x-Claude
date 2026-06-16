"""Tests for Dev10x XDG config paths and lazy/eager migration (GH-215)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
from dev10x.domain.dev10x_paths import (
    CONFIG_HOME_ENV_VAR,
    Dev10xConfigDir,
    migrate_all,
    migrate_path,
    stale_legacy_paths,
)


@pytest.fixture
def isolated_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    legacy_root = tmp_path / "claude"
    new_root = tmp_path / "config_dev10x"
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(legacy_root))
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(new_root))
    ClaudeDir.reset_cache()
    Dev10xConfigDir.reset_cache()
    yield legacy_root, new_root
    ClaudeDir.reset_cache()
    Dev10xConfigDir.reset_cache()


@pytest.mark.parametrize(
    "accessor,expected_suffix",
    [
        ("home", ""),
        ("version_yaml", "version.yml"),
        ("projects_yaml", "projects.yaml"),
        ("platforms_yaml", "platforms.yaml"),
        ("slack_config_yaml", "slack-config.yaml"),
        ("slack_review_config_yaml", "slack-config-code-review-requests.yaml"),
        ("upgrade_cleanup_projects_yaml", "upgrade-cleanup-projects.yaml"),
        ("github_bot_dir", "github-bot"),
        ("github_app_yaml", "github-bot/github-app.yaml"),
        ("gitmoji_yaml", "gitmoji.yaml"),
        ("github_reviewers_config_yaml", "github-reviewers-config.yaml"),
        ("settings_pr_merge_yaml", "settings-pr-merge.yaml"),
    ],
)
def test_accessors_resolve_under_override(
    isolated_dirs: tuple[Path, Path],
    accessor: str,
    expected_suffix: str,
) -> None:
    _, new_root = isolated_dirs
    path = getattr(Dev10xConfigDir, accessor)()
    expected = new_root / expected_suffix if expected_suffix else new_root
    assert path == expected


def test_default_root_uses_dot_config_dev10x(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_HOME_ENV_VAR, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    Dev10xConfigDir.reset_cache()
    assert Dev10xConfigDir.home() == Path.home() / ".config" / "Dev10x"


def test_xdg_config_home_is_honored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(CONFIG_HOME_ENV_VAR, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("sys.platform", "linux")
    Dev10xConfigDir.reset_cache()
    assert Dev10xConfigDir.home() == tmp_path / "xdg" / "Dev10x"
    Dev10xConfigDir.reset_cache()


def test_windows_uses_appdata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(CONFIG_HOME_ENV_VAR, raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    Dev10xConfigDir.reset_cache()
    assert Dev10xConfigDir.home() == tmp_path / "AppData" / "Dev10x"
    Dev10xConfigDir.reset_cache()


def test_migrate_path_copies_file_when_only_legacy_exists(tmp_path: Path) -> None:
    legacy = tmp_path / "old" / "file.yaml"
    current = tmp_path / "new" / "file.yaml"
    legacy.parent.mkdir()
    legacy.write_text("hello: world")
    assert migrate_path(legacy=legacy, current=current) is True
    assert current.read_text() == "hello: world"
    assert legacy.exists(), "legacy file must remain for downgrade safety"


def test_migrate_path_skips_when_current_exists(tmp_path: Path) -> None:
    legacy = tmp_path / "old" / "file.yaml"
    current = tmp_path / "new" / "file.yaml"
    legacy.parent.mkdir()
    current.parent.mkdir()
    legacy.write_text("old")
    current.write_text("new")
    assert migrate_path(legacy=legacy, current=current) is False
    assert current.read_text() == "new"


def test_migrate_path_skips_when_legacy_missing(tmp_path: Path) -> None:
    legacy = tmp_path / "old" / "absent.yaml"
    current = tmp_path / "new" / "absent.yaml"
    assert migrate_path(legacy=legacy, current=current) is False
    assert not current.exists()


def test_migrate_path_copies_directory(tmp_path: Path) -> None:
    legacy = tmp_path / "old" / "playbooks"
    current = tmp_path / "new" / "playbooks"
    legacy.mkdir(parents=True)
    (legacy / "a.yaml").write_text("a")
    (legacy / "b.yaml").write_text("b")
    assert migrate_path(legacy=legacy, current=current) is True
    assert (current / "a.yaml").read_text() == "a"
    assert (current / "b.yaml").read_text() == "b"


def test_lazy_migration_runs_on_accessor(isolated_dirs: tuple[Path, Path]) -> None:
    legacy_root, new_root = isolated_dirs
    legacy = ClaudeDir.memory_projects_yaml()
    legacy.parent.mkdir(parents=True)
    legacy.write_text("payload: 1")
    current = Dev10xConfigDir.projects_yaml()
    assert current.read_text() == "payload: 1"


def test_migrate_all_copies_every_known_pair(
    isolated_dirs: tuple[Path, Path],
) -> None:
    legacy_version = ClaudeDir.dev10x_version_yaml()
    legacy_version.parent.mkdir(parents=True, exist_ok=True)
    legacy_version.write_text("plugin_version: 0.0.0")
    legacy_platforms = ClaudeDir.platforms_yaml()
    legacy_platforms.parent.mkdir(parents=True, exist_ok=True)
    legacy_platforms.write_text("[]")

    migrated = migrate_all()
    new_paths = {p.name for p in migrated}
    assert "version.yml" in new_paths
    assert "platforms.yaml" in new_paths
    assert Dev10xConfigDir.version_yaml().read_text() == "plugin_version: 0.0.0"


def test_stale_legacy_paths_reports_only_existing(
    isolated_dirs: tuple[Path, Path],
) -> None:
    legacy_version = ClaudeDir.dev10x_version_yaml()
    legacy_version.parent.mkdir(parents=True, exist_ok=True)
    legacy_version.write_text("plugin_version: 0.0.0")
    stale = stale_legacy_paths()
    assert legacy_version in stale
    assert ClaudeDir.platforms_yaml() not in stale


@pytest.mark.parametrize(
    "legacy_accessor,current_accessor,filename",
    [
        ("gitmoji_yaml", "gitmoji_yaml", "gitmoji.yaml"),
        (
            "github_reviewers_config_yaml",
            "github_reviewers_config_yaml",
            "github-reviewers-config.yaml",
        ),
        (
            "settings_pr_merge_yaml",
            "settings_pr_merge_yaml",
            "settings-pr-merge.yaml",
        ),
    ],
)
def test_memory_dev10x_files_migrate_to_xdg_config(
    isolated_dirs: tuple[Path, Path],
    legacy_accessor: str,
    current_accessor: str,
    filename: str,
) -> None:
    legacy = getattr(ClaudeDir, legacy_accessor)()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(f"payload: {filename}")
    current = getattr(Dev10xConfigDir, current_accessor)()
    assert current.read_text() == f"payload: {filename}"


def test_migrate_all_includes_memory_dev10x_files(
    isolated_dirs: tuple[Path, Path],
) -> None:
    for accessor in (
        "gitmoji_yaml",
        "github_reviewers_config_yaml",
        "settings_pr_merge_yaml",
    ):
        legacy = getattr(ClaudeDir, accessor)()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("payload")
    migrated_names = {p.name for p in migrate_all()}
    assert "gitmoji.yaml" in migrated_names
    assert "github-reviewers-config.yaml" in migrated_names
    assert "settings-pr-merge.yaml" in migrated_names


def test_migrate_all_is_idempotent(isolated_dirs: tuple[Path, Path]) -> None:
    legacy = ClaudeDir.dev10x_version_yaml()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("plugin_version: 1.0.0")
    first = migrate_all()
    second = migrate_all()
    assert len(first) == 1
    assert second == []
