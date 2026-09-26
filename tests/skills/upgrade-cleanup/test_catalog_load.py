"""Tests for catalog_load.py: cache-path publisher extraction, settings-file
discovery, and userspace-config bootstrap (GH-1432, GH-1449)."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import catalog_load
from dev10x.skills.permission.catalog_load import (
    extract_cache_publisher,
    find_settings_files,
    init_userspace_config,
)


class TestExtractCachePublisher:
    @pytest.mark.parametrize(
        "plugin_cache,expected",
        [
            ("~/.claude/plugins/cache/Dev10x-Guru/Dev10x", "Dev10x-Guru"),
            ("~/.claude/plugins/cache/WooYek/Dev10x", "WooYek"),
            ("~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude", "Dev10x-Guru"),
        ],
    )
    def test_extracts_publisher(self, plugin_cache: str, expected: str) -> None:
        assert extract_cache_publisher(plugin_cache) == expected

    def test_returns_none_for_invalid_path(self) -> None:
        assert extract_cache_publisher("/no/cache/here") is None

    def test_returns_none_for_path_ending_at_cache(self) -> None:
        assert extract_cache_publisher("~/.claude/plugins/cache") is None


class TestFindSettingsFilesUserGlobal:
    """Regression: ~/.claude/settings.json was skipped by find_settings_files
    when include_user=True (Dev10x-Claude2#982). Both user-global files must
    be discovered so versioned plugin paths are rewritten there too."""

    @pytest.fixture()
    def fake_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        return home

    def test_includes_both_user_global_files_when_include_user(
        self,
        fake_home: Path,
    ) -> None:
        local = fake_home / ".claude" / "settings.local.json"
        global_ = fake_home / ".claude" / "settings.json"
        local.write_text("{}")
        global_.write_text("{}")

        files = find_settings_files(roots=[], include_user=True)

        assert local.resolve() in files
        assert global_.resolve() in files

    def test_includes_settings_json_even_when_local_missing(
        self,
        fake_home: Path,
    ) -> None:
        global_ = fake_home / ".claude" / "settings.json"
        global_.write_text("{}")

        files = find_settings_files(roots=[], include_user=True)

        assert global_.resolve() in files

    def test_skips_user_global_files_when_include_user_false(
        self,
        fake_home: Path,
    ) -> None:
        (fake_home / ".claude" / "settings.json").write_text("{}")
        (fake_home / ".claude" / "settings.local.json").write_text("{}")

        files = find_settings_files(roots=[], include_user=False)

        assert files == []


class TestFindSettingsFilesRoots:
    """Root-scanning behavior of find_settings_files (previously exercised
    only incidentally through fixtures elsewhere — GH-1449)."""

    @pytest.fixture(autouse=True)
    def _isolate_claude_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # find_settings_files always scans ClaudeDir.projects_dir() in
        # addition to `roots`; without isolation this walks the real
        # ~/.claude/projects tree and makes an equality assertion flaky.
        monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))

    def test_finds_settings_local_json_under_each_root(self, tmp_path: Path) -> None:
        root_a = tmp_path / "repo-a" / ".claude"
        root_b = tmp_path / "repo-b" / ".claude"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        (root_a / "settings.local.json").write_text("{}")
        (root_b / "settings.local.json").write_text("{}")

        files = find_settings_files(
            roots=[tmp_path / "repo-a", tmp_path / "repo-b"], include_user=False
        )

        assert (root_a / "settings.local.json").resolve() in files
        assert (root_b / "settings.local.json").resolve() in files

    def test_missing_root_is_skipped_without_error(self, tmp_path: Path) -> None:
        assert find_settings_files(roots=[tmp_path / "does-not-exist"], include_user=False) == []

    def test_root_without_claude_dir_yields_no_files(self, tmp_path: Path) -> None:
        (tmp_path / "repo").mkdir()

        assert find_settings_files(roots=[tmp_path / "repo"], include_user=False) == []


class TestInitUserspaceConfig:
    @pytest.fixture()
    def config_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path, Path]:
        memory = tmp_path / "projects.yaml"
        userspace = tmp_path / "upgrade-cleanup-projects.yaml"
        plugin = tmp_path / "plugin-projects.yaml"
        monkeypatch.setattr(catalog_load, "MEMORY_CONFIG", memory)
        monkeypatch.setattr(catalog_load, "USERSPACE_CONFIG", userspace)
        monkeypatch.setattr(catalog_load, "PLUGIN_CONFIG", plugin)
        return memory, userspace, plugin

    def test_noop_when_projects_yaml_exists(self, config_paths: tuple[Path, Path, Path]) -> None:
        memory, _userspace, _plugin = config_paths
        memory.write_text("roots: [/work/existing]\n")

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert memory.read_text() == "roots: [/work/existing]\n"
        assert any("already exists" in m for m in result["messages"])

    def test_migrates_legacy_userspace_into_projects_yaml(
        self, config_paths: tuple[Path, Path, Path]
    ) -> None:
        memory, userspace, _plugin = config_paths
        userspace.write_text("roots: [/work/legacy]\n")

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert memory.read_text() == "roots: [/work/legacy]\n"
        assert userspace.exists()  # left in place for downgrade safety
        assert any("Migrated" in m for m in result["messages"])

    def test_creates_from_plugin_default_when_none_exist(
        self,
        config_paths: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        memory, _userspace, plugin = config_paths
        plugin.write_text("plugin_cache: ~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude\n")
        monkeypatch.setattr(catalog_load, "_detect_plugin_cache", lambda: "/detected/cache")

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert "plugin_cache: /detected/cache" in memory.read_text()
        assert any("Created" in m for m in result["messages"])

    def test_errors_when_plugin_default_missing(
        self, config_paths: tuple[Path, Path, Path]
    ) -> None:
        result = init_userspace_config()

        assert result["exit_code"] == 1
        assert any("Plugin default config not found" in e for e in result["errors"])

    def test_rechecks_inside_lock_when_config_appears(
        self,
        config_paths: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Double-checked locking (GH-587): a config that appears between the
        outer check and the lock must not be clobbered."""
        from contextlib import contextmanager

        memory, userspace, _plugin = config_paths
        userspace.write_text("roots: [/work/legacy]\n")

        @contextmanager
        def racing_lock(path: Path, **_: object):
            memory.write_text("roots: [/work/winner]\n")
            yield

        monkeypatch.setattr("dev10x.domain.file_locks.file_lock", racing_lock)

        result = init_userspace_config()

        assert result["exit_code"] == 0
        assert memory.read_text() == "roots: [/work/winner]\n"
        assert any("already exists" in m for m in result["messages"])


class TestLoadConfig:
    """load_config / load_effective_config / load_shipped_config had no
    direct coverage in the monolithic suite (GH-1449) — they were only
    exercised incidentally via fixtures that monkeypatched around them."""

    def test_load_config_parses_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("roots: [/work/a, /work/b]\ninclude_user_settings: true\n")

        config = catalog_load.load_config(path)

        assert config["roots"] == ["/work/a", "/work/b"]
        assert config["include_user_settings"] is True

    def test_load_config_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            catalog_load.load_config(tmp_path / "missing.yaml")

    def test_load_config_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("")

        assert catalog_load.load_config(path) is None

    def test_load_shipped_config_reads_plugin_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin = tmp_path / "plugin-projects.yaml"
        plugin.write_text("plugin_cache: /detected/cache\n")
        monkeypatch.setattr(catalog_load, "PLUGIN_CONFIG", plugin)

        config = catalog_load.load_shipped_config()

        assert config["plugin_cache"] == "/detected/cache"

    def test_detect_latest_version_picks_highest_semver(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "Dev10x-Guru" / "Dev10x"
        for version in ("0.9.0", "0.10.0", "0.2.0"):
            (cache_root / version).mkdir(parents=True)

        assert catalog_load.detect_latest_version(cache_root) == "0.10.0"

    def test_detect_latest_version_missing_dir_returns_none(self, tmp_path: Path) -> None:
        assert catalog_load.detect_latest_version(tmp_path / "nope") is None
