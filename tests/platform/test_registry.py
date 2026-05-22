"""Tests for the multi-platform registry (GH-908)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.platform import PlatformConfig, Registry, known_platforms


class TestKnownPlatforms:
    """Built-in catalog covers the P1 platforms from the ticket."""

    @pytest.fixture
    def catalog(self) -> dict[str, PlatformConfig]:
        return known_platforms()

    @pytest.mark.parametrize(
        "platform_name",
        ["claude-code", "copilot-cli", "windsurf", "continue", "cursor"],
    )
    def test_includes_required_platforms(
        self,
        catalog: dict[str, PlatformConfig],
        platform_name: str,
    ) -> None:
        assert platform_name in catalog

    def test_each_entry_has_config_paths(
        self,
        catalog: dict[str, PlatformConfig],
    ) -> None:
        for cfg in catalog.values():
            assert cfg.config_dir is not None
            assert cfg.plugins_dir is not None
            assert cfg.settings_file is not None

    def test_display_name_set_per_platform(
        self,
        catalog: dict[str, PlatformConfig],
    ) -> None:
        assert catalog["copilot-cli"].display_name == "GitHub Copilot CLI"
        assert catalog["claude-code"].display_name == "Claude Code"


class TestRegistryAdd:
    """`Registry.add` persists an entry and returns the resolved config."""

    @pytest.fixture
    def registry(self, tmp_path: Path) -> Registry:
        return Registry(path=tmp_path / "platforms.yaml")

    def test_adds_from_catalog(self, registry: Registry) -> None:
        cfg = registry.add(name="windsurf")
        assert cfg.name == "windsurf"
        assert "windsurf" in str(cfg.config_dir)

    def test_add_holds_file_lock(self, registry: Registry) -> None:
        """A12: Registry.add serializes load→mutate→save via file_lock."""
        from unittest.mock import MagicMock, patch

        with patch("dev10x.platform.registry.file_lock") as mock_lock:
            mock_lock.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
            registry.add(name="windsurf")

        mock_lock.assert_called_once_with(registry.path)

    def test_remove_holds_file_lock(self, registry: Registry) -> None:
        from unittest.mock import MagicMock, patch

        registry.add(name="windsurf")
        with patch("dev10x.platform.registry.file_lock") as mock_lock:
            mock_lock.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
            registry.remove("windsurf")

        mock_lock.assert_called_once_with(registry.path)

    def test_rejects_unknown_platform(self, registry: Registry) -> None:
        with pytest.raises(ValueError, match="Unknown platform"):
            registry.add(name="not-a-real-platform")

    def test_respects_config_dir_override(
        self,
        registry: Registry,
        tmp_path: Path,
    ) -> None:
        override = tmp_path / "custom"
        override.mkdir()
        cfg = registry.add(name="cursor", config_dir=override)
        assert cfg.config_dir == override
        # plugins_dir should preserve the structural relationship
        assert cfg.plugins_dir.is_relative_to(override)

    def test_persists_playbook_override(self, registry: Registry) -> None:
        cfg = registry.add(
            name="continue",
            playbook_override="playbooks/continue.yaml",
        )
        assert cfg.playbook_override == "playbooks/continue.yaml"


class TestRegistryLoadList:
    """`Registry.list` returns persisted entries across sessions."""

    @pytest.fixture
    def registry(self, tmp_path: Path) -> Registry:
        return Registry(path=tmp_path / "platforms.yaml")

    def test_list_empty_by_default(self, registry: Registry) -> None:
        assert registry.list() == []

    def test_list_returns_registered_entries(self, registry: Registry) -> None:
        registry.add(name="claude-code")
        registry.add(name="copilot-cli")

        entries = registry.list()
        names = {e.name for e in entries}
        assert names == {"claude-code", "copilot-cli"}

    def test_list_sorted_alphabetically(self, registry: Registry) -> None:
        registry.add(name="windsurf")
        registry.add(name="claude-code")
        registry.add(name="cursor")

        entries = registry.list()
        assert [e.name for e in entries] == ["claude-code", "cursor", "windsurf"]


class TestRegistryRemove:
    """`Registry.remove` deletes a persisted entry."""

    @pytest.fixture
    def registry(self, tmp_path: Path) -> Registry:
        return Registry(path=tmp_path / "platforms.yaml")

    def test_removes_existing_entry(self, registry: Registry) -> None:
        registry.add(name="cursor")
        assert registry.remove("cursor") is True
        assert registry.list() == []

    def test_returns_false_for_unknown_entry(self, registry: Registry) -> None:
        assert registry.remove("cursor") is False


class TestRegistryRoundTrip:
    """Saved entries survive a fresh Registry instance (file-backed)."""

    def test_round_trip_preserves_config(self, tmp_path: Path) -> None:
        path = tmp_path / "platforms.yaml"

        first = Registry(path=path)
        first.add(name="continue", playbook_override="custom.yaml")

        second = Registry(path=path)
        entries = second.list()
        assert len(entries) == 1
        assert entries[0].name == "continue"
        assert entries[0].playbook_override == "custom.yaml"

    def test_windows_safe_no_symlinks_stored(self, tmp_path: Path) -> None:
        # The registry must not write symlinks — only a YAML file.
        path = tmp_path / "platforms.yaml"
        registry = Registry(path=path)
        registry.add(name="claude-code")

        assert path.is_file()
        assert not path.is_symlink()
