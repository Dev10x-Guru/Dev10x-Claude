"""Tests for `dev10x permission record-upgrade`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from dev10x.commands.permission import record_upgrade
from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir


@pytest.fixture
def claude_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
    Dev10xConfigDir.reset_cache()
    return tmp_path


def _install_plugin(*, root: Path, version: str) -> None:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "Dev10x", "version": version})
    )


def test_writes_plugin_version_to_version_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, claude_home: Path
) -> None:
    plugin_root = tmp_path / "plugin"
    _install_plugin(root=plugin_root, version="0.72.0")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))

    result = CliRunner().invoke(record_upgrade, [])
    assert result.exit_code == 0
    payload = yaml.safe_load(Dev10xConfigDir.version_yaml().read_text())
    assert payload["plugin_version"] == "0.72.0"


def test_explicit_version_overrides_plugin_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, claude_home: Path
) -> None:
    plugin_root = tmp_path / "plugin"
    _install_plugin(root=plugin_root, version="0.72.0")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))

    result = CliRunner().invoke(record_upgrade, ["--version", "9.9.9"])
    assert result.exit_code == 0
    payload = yaml.safe_load(Dev10xConfigDir.version_yaml().read_text())
    assert payload["plugin_version"] == "9.9.9"


def test_errors_when_no_version_resolvable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, claude_home: Path
) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    import dev10x.domain.install_version as iv_mod

    monkeypatch.setattr(iv_mod, "_default_plugin_root", lambda: None)

    result = CliRunner().invoke(record_upgrade, [])
    assert result.exit_code == 1
    assert "could not resolve" in result.output.lower()
