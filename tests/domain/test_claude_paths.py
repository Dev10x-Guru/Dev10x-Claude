from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir


@pytest.fixture
def home_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
    return tmp_path


@pytest.fixture
def no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLAUDE_HOME_ENV_VAR, raising=False)


@pytest.mark.parametrize(
    "accessor,expected_suffix",
    [
        ("home", ""),
        ("settings_json", "settings.json"),
        ("settings_local_json", "settings.local.json"),
        ("skills_dir", "skills"),
        ("tools_dir", "tools"),
        ("hooks_dir", "hooks"),
        ("projects_dir", "projects"),
        ("session_state_dir", "projects/_session_state"),
        ("metrics_dir", "projects/_metrics"),
        ("memory_dev10x_dir", "memory/Dev10x"),
        ("memory_projects_yaml", "memory/Dev10x/projects.yaml"),
        ("dev10x_config_dir", "Dev10x"),
        ("dev10x_version_yaml", "Dev10x/version.yml"),
        ("github_bot_dir", "Dev10x/github-bot"),
        ("github_app_yaml", "Dev10x/github-bot/github-app.yaml"),
        ("upgrade_cleanup_projects_yaml", "skills/Dev10x:upgrade-cleanup/projects.yaml"),
        ("plugins_cache_dir", "plugins/cache"),
        ("platforms_yaml", "memory/Dev10x/platforms.yaml"),
        ("slack_config_yaml", "memory/slack-config.yaml"),
        ("slack_review_config_yaml", "memory/slack-config-code-review-requests.yaml"),
    ],
)
def test_paths_resolve_under_override(
    home_override: Path,
    accessor: str,
    expected_suffix: str,
) -> None:
    path = getattr(ClaudeDir, accessor)()
    expected = home_override / expected_suffix if expected_suffix else home_override
    assert path == expected


def test_home_default_uses_home_dot_claude(no_override: None) -> None:
    assert ClaudeDir.home() == Path.home() / ".claude"


def test_override_is_read_lazily_per_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path / "first"))
    first = ClaudeDir.settings_json()
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path / "second"))
    second = ClaudeDir.settings_json()
    assert first != second
    assert first == tmp_path / "first" / "settings.json"
    assert second == tmp_path / "second" / "settings.json"


def test_override_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, "~/custom-claude")
    expected = Path("~/custom-claude").expanduser()
    assert ClaudeDir.home() == expected


def test_repeated_calls_return_cached_path(home_override: Path) -> None:
    first = ClaudeDir.settings_json()
    second = ClaudeDir.settings_json()
    assert first is second


def test_reset_cache_releases_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
    cached = ClaudeDir.settings_json()
    ClaudeDir.reset_cache()
    fresh = ClaudeDir.settings_json()
    assert cached == fresh
    assert cached is not fresh
