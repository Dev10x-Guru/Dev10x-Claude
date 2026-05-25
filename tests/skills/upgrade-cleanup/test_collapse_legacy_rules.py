"""GH-269: collapse legacy upgrade-cleanup script rules to uvx CLI form."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import update_paths


class TestCollapseLegacyUpgradeCleanupRule:
    @pytest.mark.parametrize(
        "entry,expected",
        [
            (
                "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py:*)",
                "Bash(uvx dev10x permission update-paths:*)",
            ),
            (
                "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.72.0/skills/upgrade-cleanup/scripts/update-paths.py:*)",
                "Bash(uvx dev10x permission update-paths:*)",
            ),
            (
                "Bash(/home/janusz/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.73.0/skills/upgrade-cleanup/scripts/merge-worktree-permissions.py:*)",
                "Bash(uvx dev10x permission merge-worktree:*)",
            ),
            (
                "Bash(~/.claude/plugins/cache/**/skills/upgrade-cleanup/scripts/clean-project-files.py:*)",
                "Bash(uvx dev10x permission clean:*)",
            ),
            (
                "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/enumerate-mcp.py:*)",
                "Bash(uvx dev10x permission enumerate-mcp:*)",
            ),
        ],
    )
    def test_collapses_known_scripts(self, entry: str, expected: str) -> None:
        result = update_paths.collapse_legacy_upgrade_cleanup_rule(entry)

        assert result == expected

    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(uvx dev10x permission update-paths:*)",
            "Bash(uv run dev10x:*)",
            "Bash(${CLAUDE_PLUGIN_ROOT}/skills/git-commit/scripts/foo.py:*)",
            "Bash(git log:*)",
            "mcp__plugin_Dev10x_cli__update_paths",
            "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/unknown.py:*)",
        ],
    )
    def test_ignores_unrelated_rules(self, entry: str) -> None:
        result = update_paths.collapse_legacy_upgrade_cleanup_rule(entry)

        assert result is None


class TestCollapseLegacyUpgradeCleanupRules:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_rewrites_legacy_rules_in_place(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py:*)",
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.72.0/skills/upgrade-cleanup/scripts/clean-project-files.py:*)",
                            "Bash(git log:*)",
                        ]
                    }
                },
                indent=2,
            )
        )

        count, messages = update_paths.collapse_legacy_upgrade_cleanup_rules(settings_file)

        assert count == 2
        assert len(messages) == 2
        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert "Bash(uvx dev10x permission update-paths:*)" in allow
        assert "Bash(uvx dev10x permission clean:*)" in allow
        assert "Bash(git log:*)" in allow
        for entry in allow:
            assert "upgrade-cleanup/scripts/" not in entry

    def test_dry_run_does_not_modify_file(self, settings_file: Path) -> None:
        original = json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py:*)",
                    ]
                }
            },
            indent=2,
        )
        settings_file.write_text(original)

        count, _ = update_paths.collapse_legacy_upgrade_cleanup_rules(
            settings_file,
            dry_run=True,
        )

        assert count == 1
        assert settings_file.read_text() == original

    def test_deduplicates_against_already_present_uvx_rule(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py:*)",
                            "Bash(uvx dev10x permission update-paths:*)",
                        ]
                    }
                },
                indent=2,
            )
        )

        count, _ = update_paths.collapse_legacy_upgrade_cleanup_rules(settings_file)

        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert count == 1
        assert allow.count("Bash(uvx dev10x permission update-paths:*)") == 1

    def test_no_changes_returns_zero(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(git log:*)",
                            "Bash(uvx dev10x permission update-paths:*)",
                        ]
                    }
                },
                indent=2,
            )
        )

        count, messages = update_paths.collapse_legacy_upgrade_cleanup_rules(settings_file)

        assert count == 0
        assert messages == []

    def test_empty_allow_list_returns_zero(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"permissions": {"allow": []}}))

        count, _ = update_paths.collapse_legacy_upgrade_cleanup_rules(settings_file)

        assert count == 0

    def test_invalid_json_is_skipped(self, settings_file: Path) -> None:
        settings_file.write_text("{ not json")

        count, messages = update_paths.collapse_legacy_upgrade_cleanup_rules(settings_file)

        assert count == 0
        assert messages and "SKIP" in messages[0]
