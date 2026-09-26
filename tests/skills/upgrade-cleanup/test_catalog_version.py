"""Tests for catalog_version.py: versioned plugin-cache path rewriting
(publisher + version substitution in permission rules) (GH-1432, GH-1449)."""

import json
from pathlib import Path

from dev10x.skills.permission.catalog_version import update_file


class TestUpdateFilePublisher:
    def _write(self, path: Path, rule: str) -> None:
        path.write_text(json.dumps({"permissions": {"allow": [rule]}}))

    def test_replaces_stale_publisher(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
        self._write(
            settings_file,
            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
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

    def test_replaces_publisher_only_when_version_matches(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
        self._write(
            settings_file,
            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.54.0/skills/foo.sh:*)",
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

    def test_no_changes_when_publisher_and_version_match(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
        self._write(
            settings_file,
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.54.0/skills/foo.sh:*)",
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 0

    def test_skips_publisher_replacement_when_not_specified(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
        self._write(
            settings_file,
            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
        )

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        rule = data["permissions"]["allow"][0]
        assert "WooYek/Dev10x/0.54.0" in rule

    def test_matches_dev10x_claude_plugin_name(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
        self._write(
            settings_file,
            "Bash(~/.claude/plugins/cache/WooYek/dev10x-claude/0.30.0/scripts/x.sh:*)",
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

    def test_replaces_multiple_rules_in_same_file(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
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
        offenders = [rule for rule in data["permissions"]["allow"] if "WooYek" in rule]
        assert not offenders, f"WooYek not stripped from: {offenders}"

    def test_leaves_already_current_rule_untouched(self, tmp_path: Path) -> None:
        # Mixed file: one stale rule (drives the locked rewrite) plus one
        # already-current rule (exercises the no-change branch of the
        # locked re-apply without inflating the change count).
        settings_file = tmp_path / "settings.local.json"
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/a.sh:*)",
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.54.0/skills/b.sh:*)",
                        ]
                    }
                }
            )
        )

        count, _ = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 1
        allow = json.loads(settings_file.read_text())["permissions"]["allow"]
        assert "Dev10x-Guru/Dev10x/0.54.0/skills/a.sh" in allow[0]
        assert "Dev10x-Guru/Dev10x/0.54.0/skills/b.sh" in allow[1]

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
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

    def test_invalid_json_after_replacement_skips(self, tmp_path: Path) -> None:
        # update_file operates on raw text, not parsed JSON, so a match is
        # found even in a malformed file — the SKIP guard fires only when
        # the *rewritten* text still fails to parse as JSON (i.e. the file
        # was never valid JSON to begin with).
        bad = tmp_path / "settings.local.json"
        bad.write_text(
            "not json at all Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)"
        )

        count, messages = update_file(
            bad,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 0
        assert messages and "SKIP" in messages[0]
        # The file must be left untouched — the guard must not write a
        # half-applied rewrite over a file it could not parse back.
        assert "not json at all" in bad.read_text()

    def test_no_versioned_paths_present_noop(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.local.json"
        self._write(settings_file, "Bash(git status:*)")

        count, messages = update_file(
            settings_file,
            target_version="0.54.0",
            target_publisher="Dev10x-Guru",
        )

        assert count == 0
        assert messages == []
