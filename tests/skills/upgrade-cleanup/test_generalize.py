"""Tests for the generalize feature of update_paths module."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import update_paths


class TestGeneralizePermission:
    @pytest.mark.parametrize(
        "entry,expected",
        [
            ("Bash(detect-tracker.sh PAY-123:*)", "Bash(detect-tracker.sh:*)"),
            ("Bash(gh-issue-get.sh 15:*)", "Bash(gh-issue-get.sh:*)"),
            ("Bash(gh-pr-detect.sh 42:*)", "Bash(gh-pr-detect.sh:*)"),
            ("Bash(generate-commit-list.sh 42:*)", "Bash(generate-commit-list.sh:*)"),
            ("Bash(generate-commit-list.sh PLACEHOLDER:*)", "Bash(generate-commit-list.sh:*)"),
            ("Bash(extract-session.sh abc123:*)", "Bash(extract-session.sh:*)"),
        ],
    )
    def test_generalizes_script_args(self, entry: str, expected: str) -> None:
        result = update_paths.generalize_permission(entry)

        assert result == expected

    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(git log:*)",
            "Bash(gh pr view:*)",
            "Bash(/tmp/Dev10x/bin/mktmp.sh:*)",
            "mcp__plugin_Dev10x_*",
        ],
    )
    def test_leaves_stable_permissions_unchanged(self, entry: str) -> None:
        result = update_paths.generalize_permission(entry)

        assert result is None

    def test_generalizes_temp_file_hashes(self) -> None:
        entry = "Write(/tmp/Dev10x/git/msg.AbCdEfGh.txt)"

        result = update_paths.generalize_permission(entry)

        assert result == "Write(/tmp/Dev10x/git/*)"

    def test_generalizes_quoted_json_blob_arg(self) -> None:
        """GH-315: single quoted JSON-blob arg must collapse to Bash(<script>:*).

        The argument contains colons (e.g. ``"week":"2026-W21"``).  The old
        ``[^):]+`` pattern stopped at the first colon, leaving a malformed
        ``Bash(<script>:*:<rest>)`` rule that Claude Code rejects at load time.
        """
        entry = (
            "Bash(~/.claude/tools/append-weekly-history.py"
            ' \'{"week":"2026-W21","start":"2026-05-18","reviews":13}\')'
        )

        result = update_paths.generalize_permission(entry)

        assert result == "Bash(~/.claude/tools/append-weekly-history.py:*)"

    @pytest.mark.parametrize(
        "entry,expected",
        [
            (
                "Bash(~/.claude/tools/my-script.sh --flag value)",
                "Bash(~/.claude/tools/my-script.sh:*)",
            ),
            (
                "Bash(~/.claude/tools/my-script.py arg1 arg2)",
                "Bash(~/.claude/tools/my-script.py:*)",
            ),
        ],
    )
    def test_generalizes_script_with_args_no_colon(
        self,
        entry: str,
        expected: str,
    ) -> None:
        result = update_paths.generalize_permission(entry)

        assert result == expected


class TestGeneralizePermissions:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_replaces_session_specific_with_generalized(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(git log:*)",
                            "Bash(detect-tracker.sh PAY-123:*)",
                            "Bash(gh-pr-detect.sh 42:*)",
                        ]
                    }
                }
            )
            + "\n"
        )

        count, messages = update_paths.generalize_permissions(settings_file)

        assert count == 2
        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert "Bash(git log:*)" in allow
        assert "Bash(detect-tracker.sh:*)" in allow
        assert "Bash(gh-pr-detect.sh:*)" in allow
        assert "Bash(detect-tracker.sh PAY-123:*)" not in allow

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(detect-tracker.sh PAY-123:*)"]}}) + "\n"
        )
        original = settings_file.read_text()

        count, messages = update_paths.generalize_permissions(
            settings_file,
            dry_run=True,
        )

        assert count == 1
        assert settings_file.read_text() == original

    def test_no_changes_when_already_generalized(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(git log:*)", "Bash(gh pr view:*)"]}})
            + "\n"
        )

        count, messages = update_paths.generalize_permissions(settings_file)

        assert count == 0
        assert messages == []

    def test_skips_invalid_json(self, settings_file: Path) -> None:
        settings_file.write_text("{invalid json}")

        count, messages = update_paths.generalize_permissions(settings_file)

        assert count == 0
        assert any("SKIP" in m for m in messages)

    def test_skips_when_generalized_already_exists(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(detect-tracker.sh PAY-123:*)",
                            "Bash(detect-tracker.sh:*)",
                        ]
                    }
                }
            )
            + "\n"
        )

        count, messages = update_paths.generalize_permissions(settings_file)

        assert count == 0

    def test_preserves_other_settings_keys(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": ["Bash(detect-tracker.sh PAY-123:*)"],
                        "deny": ["something"],
                    },
                    "hooks": {"PreToolUse": []},
                }
            )
            + "\n"
        )

        update_paths.generalize_permissions(settings_file)

        data = json.loads(settings_file.read_text())
        assert data["permissions"]["deny"] == ["something"]
        assert data["hooks"] == {"PreToolUse": []}
