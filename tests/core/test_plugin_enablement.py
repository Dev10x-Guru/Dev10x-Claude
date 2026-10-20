"""GH-1557: whether a plugin key is enabled, read from Claude Code settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dev10x.core.plugin_enablement import (
    PluginSettingsError,
    enabled_plugins,
    is_plugin_enabled,
    plugin_ids,
    settings_files,
)
from dev10x.core.plugin_map import PluginMap, parse_plugin_map

CORE_ID = "dev10x@Dev10x-Guru"
LEGACY_ID = "Dev10x@Dev10x-Guru"
QA_ID = "dev10x-qa@Dev10x-Guru"


@pytest.fixture
def claude_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "claude-home"
    home.mkdir()
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(home))
    return home


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".claude").mkdir(parents=True)
    return root


@pytest.fixture
def plugin_map() -> PluginMap:
    return parse_plugin_map(
        data={
            "marketplace": "Dev10x-Guru",
            "extracted": ["qa"],
            "plugin_names": {"core": "dev10x", "coding": "dev10x-coding", "qa": "dev10x-qa"},
            "plugins": {"core": ["afk"], "coding": ["git"], "qa": ["tts"]},
        }
    )


def _settings(*, path: Path, plugins: Any) -> None:
    path.write_text(json.dumps({"enabledPlugins": plugins}))


@pytest.fixture
def user_settings(claude_home: Path) -> Path:
    return claude_home / "settings.json"


@pytest.fixture
def project_settings(project: Path) -> Path:
    return project / ".claude" / "settings.json"


@pytest.fixture
def local_settings(project: Path) -> Path:
    return project / ".claude" / "settings.local.json"


class TestSettingsFiles:
    def test_user_project_then_local(
        self,
        project: Path,
        user_settings: Path,
        project_settings: Path,
        local_settings: Path,
    ) -> None:
        assert settings_files(project_dir=project) == [
            user_settings,
            project_settings,
            local_settings,
        ]

    def test_user_only_without_a_project(self, user_settings: Path) -> None:
        assert settings_files(project_dir=None) == [user_settings]


class TestEnabledPlugins:
    def test_narrower_file_wins_per_key(
        self,
        project: Path,
        user_settings: Path,
        project_settings: Path,
        local_settings: Path,
    ) -> None:
        _settings(path=user_settings, plugins={CORE_ID: True, QA_ID: True, "x@m": True})
        _settings(path=project_settings, plugins={CORE_ID: False, QA_ID: False})
        _settings(path=local_settings, plugins={CORE_ID: True})
        assert enabled_plugins(project_dir=project) == {CORE_ID: True, QA_ID: False, "x@m": True}

    def test_missing_files_read_as_empty(self, project: Path, claude_home: Path) -> None:
        assert enabled_plugins(project_dir=project) == {}

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("{not json", id="malformed-json"),
            pytest.param("[]", id="not-an-object"),
            pytest.param('{"enabledPlugins": []}', id="plugins-not-an-object"),
        ],
    )
    def test_unreadable_settings_raise(
        self,
        project: Path,
        project_settings: Path,
        claude_home: Path,
        content: str,
    ) -> None:
        project_settings.write_text(content)
        with pytest.raises(PluginSettingsError):
            enabled_plugins(project_dir=project)

    def test_unreadable_file_raises(self, project: Path, project_settings: Path) -> None:
        project_settings.mkdir()
        with pytest.raises(PluginSettingsError):
            enabled_plugins(project_dir=project)


class TestPluginIds:
    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("core", frozenset({CORE_ID.casefold()})),
            ("coding", frozenset({CORE_ID.casefold(), LEGACY_ID.casefold()})),
            ("qa", frozenset({QA_ID.casefold()})),
        ],
    )
    def test_resolves_install_ids(
        self,
        plugin_map: PluginMap,
        key: str,
        expected: frozenset[str],
    ) -> None:
        assert plugin_ids(key=key, plugin_map=plugin_map) == expected

    def test_extracted_key_without_a_name_uses_the_scheme(self) -> None:
        bare = parse_plugin_map(data={"marketplace": "M", "extracted": ["db"]})
        assert plugin_ids(key="db", plugin_map=bare) == frozenset({"dev10x-db@m"})


class TestIsPluginEnabled:
    @pytest.mark.parametrize(
        ("plugins", "expected"),
        [
            pytest.param({CORE_ID: False}, False, id="current-id-off"),
            pytest.param({LEGACY_ID: False}, False, id="legacy-id-off"),
            pytest.param({"DEV10X@dev10x-guru": False}, False, id="other-casing-off"),
            pytest.param({CORE_ID: True}, True, id="current-id-on"),
            pytest.param({"other@m": False}, True, id="unnamed-core-hosted"),
        ],
    )
    def test_core_hosted_key(
        self,
        project: Path,
        local_settings: Path,
        claude_home: Path,
        plugin_map: PluginMap,
        plugins: dict[str, bool],
        expected: bool,
    ) -> None:
        _settings(path=local_settings, plugins=plugins)
        assert (
            is_plugin_enabled(key="coding", project_dir=project, plugin_map=plugin_map) is expected
        )

    def test_narrower_current_id_beats_broader_legacy_id(
        self,
        project: Path,
        user_settings: Path,
        local_settings: Path,
        plugin_map: PluginMap,
    ) -> None:
        _settings(path=user_settings, plugins={LEGACY_ID: True})
        _settings(path=local_settings, plugins={CORE_ID: False})
        assert is_plugin_enabled(key="coding", project_dir=project, plugin_map=plugin_map) is False

    @pytest.mark.parametrize(
        ("plugins", "expected"),
        [
            pytest.param({QA_ID: True}, True, id="installed"),
            pytest.param({QA_ID: False}, False, id="disabled"),
            pytest.param({CORE_ID: True}, False, id="only-core-installed"),
        ],
    )
    def test_extracted_key(
        self,
        project: Path,
        user_settings: Path,
        plugin_map: PluginMap,
        plugins: dict[str, bool],
        expected: bool,
    ) -> None:
        _settings(path=user_settings, plugins=plugins)
        assert is_plugin_enabled(key="qa", project_dir=project, plugin_map=plugin_map) is expected

    def test_malformed_settings_fail_toward_enabled(
        self,
        project: Path,
        user_settings: Path,
        local_settings: Path,
        plugin_map: PluginMap,
    ) -> None:
        _settings(path=user_settings, plugins={QA_ID: False})
        local_settings.write_text("{broken")
        assert is_plugin_enabled(key="qa", project_dir=project, plugin_map=plugin_map) is True

    def test_defaults_to_the_shipped_plugin_map(
        self,
        project: Path,
        local_settings: Path,
        claude_home: Path,
    ) -> None:
        _settings(path=local_settings, plugins={CORE_ID: False})
        assert is_plugin_enabled(key="coding", project_dir=project) is False
