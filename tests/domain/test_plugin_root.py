"""Tests for the shared plugin-root resolver (GH-919)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.plugin_root import (
    is_plugin_root,
    latest_installed_root,
    resolve_plugin_root,
)


def _make_plugin_root(path: Path, *, version: str = "0.92.0") -> Path:
    manifest_dir = path / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(json.dumps({"name": "Dev10x", "version": version}))
    return path


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """An installed plugin cache holding two versions of one plugin."""
    plugin_dir = tmp_path / "cache" / "Dev10x-Guru" / "dev10x-claude"
    _make_plugin_root(plugin_dir / "0.9.0", version="0.9.0")
    _make_plugin_root(plugin_dir / "0.10.0", version="0.10.0")
    return tmp_path / "cache"


class TestIsPluginRoot:
    """A plugin root is identified by its ``.claude-plugin/plugin.json``."""

    def test_manifest_present(self, tmp_path: Path) -> None:
        assert is_plugin_root(_make_plugin_root(tmp_path))

    def test_manifest_absent(self, tmp_path: Path) -> None:
        assert not is_plugin_root(tmp_path)


class TestLatestInstalledRoot:
    """The newest semver directory under the cache wins."""

    def test_picks_highest_version(self, cache_dir: Path) -> None:
        resolved = latest_installed_root(cache_dir=cache_dir)
        assert resolved is not None
        assert resolved.name == "0.10.0"

    def test_missing_cache_returns_none(self, tmp_path: Path) -> None:
        assert latest_installed_root(cache_dir=tmp_path / "absent") is None

    def test_version_dir_without_manifest_is_ignored(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "cache" / "Pub" / "Dev10x"
        (plugin_dir / "9.9.9").mkdir(parents=True)
        _make_plugin_root(plugin_dir / "0.1.0", version="0.1.0")
        resolved = latest_installed_root(cache_dir=tmp_path / "cache")
        assert resolved is not None
        assert resolved.name == "0.1.0"

    def test_unknown_plugin_dir_name_is_ignored(self, tmp_path: Path) -> None:
        _make_plugin_root(tmp_path / "cache" / "Pub" / "some-other-plugin" / "1.0.0")
        assert latest_installed_root(cache_dir=tmp_path / "cache") is None


class TestResolvePluginRoot:
    """Resolution order: override → checkout walk-up → env → installed cache."""

    def test_override_wins(self, tmp_path: Path, cache_dir: Path) -> None:
        override = _make_plugin_root(tmp_path / "explicit")
        assert resolve_plugin_root(override=override, cache_dir=cache_dir) == override

    def test_override_returned_verbatim_without_manifest(self, tmp_path: Path) -> None:
        override = tmp_path / "bare"
        override.mkdir()
        assert resolve_plugin_root(override=override) == override

    def test_checkout_walk_up_resolves_this_repo(self) -> None:
        resolved = resolve_plugin_root(environ={})
        assert resolved is not None
        assert is_plugin_root(resolved)
        assert (resolved / "src" / "dev10x").is_dir()


class TestResolveWithoutCheckout:
    """From an installed wheel the walk-up fails and the fallbacks carry it."""

    @pytest.fixture(autouse=True)
    def no_checkout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dev10x.domain.plugin_root._checkout_root", lambda: None)

    def test_env_root_used(self, tmp_path: Path, cache_dir: Path) -> None:
        env_root = _make_plugin_root(tmp_path / "from-env")
        resolved = resolve_plugin_root(
            environ={"CLAUDE_PLUGIN_ROOT": str(env_root)},
            cache_dir=cache_dir,
        )
        assert resolved == env_root

    def test_stale_env_root_falls_back_to_cache(self, tmp_path: Path, cache_dir: Path) -> None:
        resolved = resolve_plugin_root(
            environ={"CLAUDE_PLUGIN_ROOT": str(tmp_path / "deleted")},
            cache_dir=cache_dir,
        )
        assert resolved is not None
        assert resolved.name == "0.10.0"

    def test_cache_used_when_env_unset(self, cache_dir: Path) -> None:
        resolved = resolve_plugin_root(environ={}, cache_dir=cache_dir)
        assert resolved is not None
        assert resolved.name == "0.10.0"

    def test_nothing_installed_returns_none(self, tmp_path: Path) -> None:
        assert resolve_plugin_root(environ={}, cache_dir=tmp_path / "absent") is None
