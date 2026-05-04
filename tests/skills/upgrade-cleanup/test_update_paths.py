"""Tests for publisher rename handling in update-paths.py."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission.update_paths import (
    extract_cache_publisher,
    find_settings_files,
    update_file,
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


class TestUpdateFilePublisher:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_replaces_stale_publisher(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "Dev10x-Guru/Dev10x/0.54.0" in rule
        assert "WooYek" not in rule

    def test_replaces_publisher_only_when_version_matches(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.54.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "Dev10x-Guru/Dev10x/0.54.0" in rule

    def test_no_changes_when_publisher_and_version_match(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.54.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 0

    def test_skips_publisher_replacement_when_not_specified(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "WooYek/Dev10x/0.54.0" in rule

    def test_matches_dev10x_claude_plugin_name(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/dev10x-claude/0.30.0/scripts/x.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "Dev10x-Guru/dev10x-claude/0.54.0" in rule

    def test_replaces_multiple_rules_in_same_file(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/a.sh:*)",
                            "Bash(git log:*)",
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/b.sh:*)",
                        ]
                    }
                }
            )
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 2
        data = json.loads(settings_file.read_text())
        for rule in data["permissions"]["allow"]:
            assert "WooYek" not in rule

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        content = json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
                    ]
                }
            }
        )
        settings_file.write_text(content)

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
            dry_run=True,
        )

        assert count == 1
        assert settings_file.read_text() == content


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
