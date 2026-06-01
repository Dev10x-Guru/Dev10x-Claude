from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
from dev10x.domain.install_version import (
    InstallState,
    install_state,
    read_applied_version,
    read_latest_installed_version,
    read_plugin_version,
    read_running_hook_version,
    record_upgrade,
    write_applied_version,
)


@pytest.fixture
def claude_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
    Dev10xConfigDir.reset_cache()
    return tmp_path


@pytest.fixture
def plugin_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "Dev10x", "version": "0.72.0"})
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    return root


def test_read_plugin_version_from_manifest(plugin_root: Path) -> None:
    assert read_plugin_version() == "0.72.0"


def test_read_plugin_version_explicit_root(plugin_root: Path) -> None:
    assert read_plugin_version(plugin_root=plugin_root) == "0.72.0"


def test_read_plugin_version_missing_manifest(tmp_path: Path) -> None:
    assert read_plugin_version(plugin_root=tmp_path) is None


def test_read_plugin_version_malformed_json(tmp_path: Path) -> None:
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{not json")
    assert read_plugin_version(plugin_root=tmp_path) is None


def test_read_applied_version_missing_file(claude_home: Path) -> None:
    assert read_applied_version() is None


def test_read_applied_version_returns_recorded_value(claude_home: Path) -> None:
    write_applied_version(plugin_version="0.71.0")
    assert read_applied_version() == "0.71.0"


def test_read_applied_version_rejects_non_string(claude_home: Path) -> None:
    path = Dev10xConfigDir.version_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"plugin_version": 0.72}))
    assert read_applied_version() is None


def test_write_applied_version_persists_timestamp(claude_home: Path) -> None:
    moment = datetime(2026, 5, 17, 12, 30, tzinfo=UTC)
    written = write_applied_version(plugin_version="0.72.0", now=moment)
    payload = yaml.safe_load(written.read_text())
    assert payload == {
        "plugin_version": "0.72.0",
        "upgraded_at": moment.isoformat(),
    }


def test_install_state_needs_bootstrap_when_config_missing(
    claude_home: Path, plugin_root: Path
) -> None:
    state = install_state()
    assert state.needs_bootstrap is True
    assert state.needs_upgrade is False


def test_install_state_needs_upgrade_when_version_missing(
    claude_home: Path, plugin_root: Path
) -> None:
    Dev10xConfigDir.home().mkdir(parents=True)
    state = install_state()
    assert state.needs_bootstrap is False
    assert state.needs_upgrade is True


def test_install_state_current_when_versions_match(claude_home: Path, plugin_root: Path) -> None:
    Dev10xConfigDir.home().mkdir(parents=True)
    write_applied_version(plugin_version="0.72.0")
    state = install_state()
    assert state.needs_bootstrap is False
    assert state.needs_upgrade is False


def test_install_state_needs_upgrade_when_versions_differ(
    claude_home: Path, plugin_root: Path
) -> None:
    Dev10xConfigDir.home().mkdir(parents=True)
    write_applied_version(plugin_version="0.71.0")
    state = install_state()
    assert state.needs_upgrade is True


def test_install_state_silent_when_plugin_version_unknown(
    claude_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # Walk-up fallback inside this test tree will not find a manifest.
    monkeypatch.chdir(tmp_path)
    state = InstallState(
        config_present=True,
        plugin_version=None,
        applied_version="0.71.0",
    )
    assert state.needs_upgrade is False


def test_record_upgrade_writes_resolved_version(claude_home: Path, plugin_root: Path) -> None:
    result = record_upgrade()
    assert isinstance(result, SuccessResult)
    assert result.value["version"] == "0.72.0"
    assert result.value["path"].endswith("version.yml")
    assert read_applied_version() == "0.72.0"


def test_record_upgrade_explicit_version_overrides_manifest(
    claude_home: Path, plugin_root: Path
) -> None:
    result = record_upgrade(version="9.9.9")
    assert isinstance(result, SuccessResult)
    assert result.value["version"] == "9.9.9"
    assert read_applied_version() == "9.9.9"


def test_record_upgrade_errors_when_unresolvable(
    claude_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    import dev10x.domain.install_version as iv_mod

    monkeypatch.setattr(iv_mod, "_default_plugin_root", lambda: None)
    result = record_upgrade()
    assert isinstance(result, ErrorResult)
    assert "could not resolve" in result.error.lower()


class TestReadRunningHookVersion:
    """GH-407: read_running_hook_version() reads from $CLAUDE_PLUGIN_ROOT."""

    def test_returns_version_from_plugin_root(self, plugin_root: Path) -> None:
        assert read_running_hook_version() == "0.72.0"

    def test_returns_none_when_no_env_and_no_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        assert read_running_hook_version(plugin_root=tmp_path) is None

    def test_accepts_explicit_plugin_root(self, plugin_root: Path) -> None:
        assert read_running_hook_version(plugin_root=plugin_root) == "0.72.0"


class TestReadLatestInstalledVersion:
    """GH-407: read_latest_installed_version() scans the plugin cache."""

    def test_returns_highest_semver_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir

        cache_base = tmp_path / "plugins" / "cache" / "Dev10x-Guru" / "dev10x-claude"
        for ver in ("0.72.0", "0.76.0", "0.73.0"):
            (cache_base / ver).mkdir(parents=True)
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        assert read_latest_installed_version() == "0.76.0"

    def test_returns_none_when_cache_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        assert read_latest_installed_version() is None

    def test_returns_none_when_cache_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir

        cache_base = tmp_path / "plugins" / "cache" / "Dev10x-Guru" / "dev10x-claude"
        cache_base.mkdir(parents=True)
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        assert read_latest_installed_version() is None

    def test_accepts_explicit_cache_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "custom-cache"
        for ver in ("0.10.0", "0.9.0"):
            (cache_dir / ver).mkdir(parents=True)

        assert read_latest_installed_version(cache_dir=cache_dir) == "0.10.0"
