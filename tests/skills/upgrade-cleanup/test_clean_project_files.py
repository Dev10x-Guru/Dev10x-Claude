"""Tests for the clean_project_files module."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import clean_project_files as clean_mod


class TestIsShellFragment:
    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(do something)",
            "Bash(done)",
            "Bash(fi)",
            "Bash(for x in list)",
            "Bash(while true)",
            "Bash(break)",
            "Bash(then echo)",
            "Bash(else exit 1)",
            "Bash(if [ -f foo ])",
            "Bash(case $x in)",
            "Bash(esac)",
            "Bash(select item in list)",
            "Bash(until done)",
        ],
    )
    def test_detects_shell_fragments(self, rule: str) -> None:
        assert clean_mod.is_shell_fragment(rule) is True

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git log:*)",
            "Bash(docker compose up)",
            "Bash(find . -name foo)",
        ],
    )
    def test_rejects_normal_commands(self, rule: str) -> None:
        assert clean_mod.is_shell_fragment(rule) is False


class TestIsOldVersion:
    def test_detects_old_version(self) -> None:
        rule = (
            "Bash(/home/user/.claude/plugins/cache/Dev10x-Guru/"
            "dev10x-claude/0.16.0/scripts/foo.sh:*)"
        )

        assert clean_mod.is_old_version(rule, "0.33.0") is True

    def test_current_version_is_not_old(self) -> None:
        rule = (
            "Bash(/home/user/.claude/plugins/cache/Dev10x-Guru/"
            "dev10x-claude/0.33.0/scripts/foo.sh:*)"
        )

        assert clean_mod.is_old_version(rule, "0.33.0") is False

    def test_returns_false_when_no_version_in_rule(self) -> None:
        assert clean_mod.is_old_version("Bash(git log:*)", "0.33.0") is False

    def test_returns_false_when_no_current_version(self) -> None:
        rule = (
            "Bash(/home/user/.claude/plugins/cache/Dev10x-Guru/"
            "dev10x-claude/0.16.0/scripts/foo.sh:*)"
        )

        assert clean_mod.is_old_version(rule, None) is False

    def test_detects_old_version_with_alternate_org(self) -> None:
        rule = (
            "Bash(/home/user/.claude/plugins/cache/WooYek/dev10x-claude/0.16.0/scripts/foo.sh:*)"
        )

        assert clean_mod.is_old_version(rule, "0.33.0") is True

    def test_detects_old_version_with_lowercase_plugin_name(self) -> None:
        rule = "Bash(/home/user/.claude/plugins/cache/Dev10x-Guru/dev10x/0.56.0/scripts/foo.sh:*)"

        assert clean_mod.is_old_version(rule, "0.58.0") is True


class TestHasLeakedSecret:
    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(LINEAR_KEY=lin_api_abc123 some-command)",
            "Bash(DATABASE_URL=postgres://user:pass@host/db command)",
            "Bash(API_KEY=sk_live_abcdef1234 curl)",
            "Bash(TOKEN=eyJhbGciOiJIUzI1NiJ9 command)",
        ],
    )
    def test_detects_leaked_secrets(self, rule: str) -> None:
        assert clean_mod.has_leaked_secret(rule) is True

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git log:*)",
            "Bash(GIT_SEQUENCE_EDITOR=: git rebase)",
            "mcp__plugin_Dev10x_cli__detect_tracker",
        ],
    )
    def test_ignores_non_secrets(self, rule: str) -> None:
        assert clean_mod.has_leaked_secret(rule) is False


class TestIsHookEnabled:
    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(gh pr create:*)",
            "Bash(git push:*)",
            "Bash(git push origin main)",
            "Bash(git rebase -i:*)",
            "Bash(git commit -m:*)",
            "Bash(gh pr checks:*)",
        ],
    )
    def test_detects_hook_enabled_rules(self, rule: str) -> None:
        assert clean_mod.is_hook_enabled(rule) is True

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git log:*)",
            "Bash(gh pr view:*)",
            "Bash(docker compose up)",
            "mcp__plugin_Dev10x_cli__detect_tracker",
        ],
    )
    def test_rejects_non_hook_enabled_rules(self, rule: str) -> None:
        assert clean_mod.is_hook_enabled(rule) is False


class TestClassifyRules:
    GLOBAL_RULES = {
        "Bash(git log:*)",
        "Bash(gh pr view:*)",
        "mcp__claude_ai_Linear__*",
        "mcp__plugin_Dev10x_*",
    }

    def test_classifies_exact_duplicates(self) -> None:
        rules = ["Bash(git log:*)", "Bash(gh pr view:*)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.exact_duplicates == rules
        assert result.kept == []

    def test_mcp_wildcards_no_longer_remove_individual_tools(self) -> None:
        rules = ["mcp__claude_ai_Linear__get_issue", "mcp__plugin_Dev10x_cli__push"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.kept == rules

    def test_classifies_old_versions(self) -> None:
        rules = [
            "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/dev10x-claude/0.4.0/scripts/foo.sh:*)",
        ]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert len(result.old_versions) == 1
        assert result.kept == []

    def test_classifies_env_noise(self) -> None:
        rules = [
            "Bash(GIT_SEQUENCE_EDITOR=: git rebase)",
            "Bash(DATABASE_URL=postgres://host/db command)",
        ]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert len(result.env_noise) == 2

    def test_classifies_shell_fragments(self) -> None:
        rules = ["Bash(do something)", "Bash(done)", "Bash(fi)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert len(result.shell_fragments) == 3

    def test_classifies_double_slash_paths(self) -> None:
        rules = ["Read(//work/example/app-pos/src/file.py)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert len(result.double_slash) == 1

    def test_keeps_legitimate_rules(self) -> None:
        rules = [
            "Bash(docker compose up)",
            "Read(/work/my-project/src/file.py)",
        ]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.kept == rules
        assert result.total_removed == 0

    def test_flags_leaked_secrets_alongside_classification(self) -> None:
        rules = ["Bash(LINEAR_KEY=lin_api_abc123 some-command)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert len(result.leaked_secrets) == 1
        assert len(result.env_noise) == 1

    def test_keeps_hook_enabled_rules(self) -> None:
        rules = ["Bash(git push:*)", "Bash(gh pr create:*)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.hook_enabled == rules
        assert result.kept == rules
        assert result.total_removed == 0

    def test_hook_enabled_takes_precedence_over_duplicate(self) -> None:
        global_rules = self.GLOBAL_RULES | {"Bash(git push:*)"}
        rules = ["Bash(git push:*)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=global_rules,
            current_version="0.33.0",
        )

        assert result.hook_enabled == ["Bash(git push:*)"]
        assert result.kept == ["Bash(git push:*)"]
        assert result.exact_duplicates == []

    def test_total_removed_counts_all_categories(self) -> None:
        rules = [
            "Bash(git log:*)",
            "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/dev10x-claude/0.4.0/x.sh:*)",
            "Bash(GIT_SEQUENCE_EDITOR=: git rebase)",
            "Bash(fi)",
            "Read(//work/example/file.py)",
        ]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.total_removed == 5


class TestCleanFile:
    GLOBAL_RULES = {"Bash(git log:*)", "mcp__claude_ai_Linear__*"}

    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_removes_redundant_rules(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(git log:*)",
                            "mcp__claude_ai_Linear__get_issue",
                            "Bash(docker compose up)",
                        ]
                    }
                }
            )
            + "\n"
        )

        result, messages = clean_mod.clean_file(
            settings_file,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.total_removed == 1
        data = json.loads(settings_file.read_text())
        assert "Bash(git log:*)" not in data["permissions"]["allow"]
        assert "mcp__claude_ai_Linear__get_issue" in data["permissions"]["allow"]
        assert "Bash(docker compose up)" in data["permissions"]["allow"]

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(git log:*)"]}}) + "\n"
        )
        original = settings_file.read_text()

        result, messages = clean_mod.clean_file(
            settings_file,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
            dry_run=True,
        )

        assert result.total_removed == 1
        assert settings_file.read_text() == original

    def test_no_changes_when_all_clean(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(docker compose up)"]}}) + "\n"
        )

        result, messages = clean_mod.clean_file(
            settings_file,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.total_removed == 0
        assert messages == []

    def test_skips_invalid_json(self, settings_file: Path) -> None:
        settings_file.write_text("{invalid json}")

        result, messages = clean_mod.clean_file(
            settings_file,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result is None
        assert any("SKIP" in m for m in messages)

    def test_preserves_other_settings_keys(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": ["Bash(git log:*)"],
                        "deny": ["something"],
                    },
                    "hooks": {"PreToolUse": []},
                }
            )
            + "\n"
        )

        clean_mod.clean_file(
            settings_file,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        data = json.loads(settings_file.read_text())
        assert data["permissions"]["deny"] == ["something"]
        assert data["hooks"] == {"PreToolUse": []}

    def test_keeps_hook_enabled_rules(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(git log:*)",
                            "Bash(git push:*)",
                            "Bash(docker compose up)",
                        ]
                    }
                }
            )
            + "\n"
        )

        result, messages = clean_mod.clean_file(
            settings_file,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.total_removed == 1
        data = json.loads(settings_file.read_text())
        assert "Bash(git push:*)" in data["permissions"]["allow"]
        assert "Bash(docker compose up)" in data["permissions"]["allow"]
        assert "Bash(git log:*)" not in data["permissions"]["allow"]

    def test_handles_empty_allow_list(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"permissions": {"allow": []}}) + "\n")

        result, messages = clean_mod.clean_file(
            settings_file,
            global_rules=self.GLOBAL_RULES,
            current_version="0.33.0",
        )

        assert result.total_removed == 0
        assert messages == []


class TestIsStalePublisher:
    def test_detects_stale_publisher(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "cache"
        (cache_root / "Dev10x-Guru").mkdir(parents=True)
        rule = "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)"

        assert clean_mod.is_stale_publisher(rule, cache_root=cache_root) is True

    def test_returns_false_for_existing_publisher(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "cache"
        (cache_root / "Dev10x-Guru").mkdir(parents=True)
        rule = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.54.0/skills/foo.sh:*)"

        assert clean_mod.is_stale_publisher(rule, cache_root=cache_root) is False

    def test_returns_false_for_non_plugin_rule(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "cache"
        (cache_root / "Dev10x-Guru").mkdir(parents=True)

        assert clean_mod.is_stale_publisher("Bash(git log:*)", cache_root=cache_root) is False

    def test_returns_false_when_cache_root_is_none(self) -> None:
        rule = "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)"

        assert clean_mod.is_stale_publisher(rule, cache_root=None) is False

    def test_matches_dev10x_claude_plugin_name(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "cache"
        (cache_root / "Dev10x-Guru").mkdir(parents=True)
        rule = "Bash(~/.claude/plugins/cache/WooYek/dev10x-claude/0.30.0/scripts/x.sh:*)"

        assert clean_mod.is_stale_publisher(rule, cache_root=cache_root) is True


class TestClassifyRulesStalePublisher:
    GLOBAL_RULES: set[str] = set()

    def test_classifies_stale_publisher_rules(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "cache"
        (cache_root / "Dev10x-Guru").mkdir(parents=True)
        rules = [
            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.48.0/skills/foo.sh:*)",
        ]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.54.0",
            cache_root=cache_root,
        )

        assert len(result.stale_publisher) == 1
        assert result.total_removed == 1

    def test_stale_publisher_takes_precedence_over_old_version(
        self,
        tmp_path: Path,
    ) -> None:
        cache_root = tmp_path / "cache"
        (cache_root / "Dev10x-Guru").mkdir(parents=True)
        rules = [
            "Bash(~/.claude/plugins/cache/WooYek/Dev10x/0.30.0/skills/foo.sh:*)",
        ]

        result = clean_mod.classify_rules(
            rules,
            global_rules=self.GLOBAL_RULES,
            current_version="0.54.0",
            cache_root=cache_root,
        )

        assert len(result.stale_publisher) == 1
        assert len(result.old_versions) == 0


class TestBasePermissionsPreserved:
    def test_base_permissions_kept_even_when_covered_by_global_wildcard(self) -> None:
        global_rules = {"Bash(git develop-:*)"}
        base_permissions = {
            "Bash(git develop-log:*)",
            "Bash(git develop-diff:*)",
        }
        rules = ["Bash(git develop-log:*)", "Bash(git develop-diff:*)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=global_rules,
            current_version="0.57.0",
            base_permissions=base_permissions,
        )

        assert result.kept == rules
        assert result.total_removed == 0

    def test_base_permissions_kept_even_when_exact_duplicate_of_global(self) -> None:
        global_rules = {"Bash(git checkout:*)"}
        base_permissions = {"Bash(git checkout:*)"}
        rules = ["Bash(git checkout:*)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=global_rules,
            current_version="0.57.0",
            base_permissions=base_permissions,
        )

        assert result.kept == rules
        assert result.total_removed == 0


class TestWildcardBypassDetection:
    def test_detects_bash_wildcard_bypass(self) -> None:
        rules = ["Bash(*)", "Bash(git log)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=set(),
            current_version=None,
        )

        assert result.wildcard_bypasses == ["Bash(*)"]

    def test_detects_read_write_wildcard_bypass(self) -> None:
        rules = ["Read(*)", "Write(*)", "Edit(*)"]

        result = clean_mod.classify_rules(
            rules,
            global_rules=set(),
            current_version=None,
        )

        assert len(result.wildcard_bypasses) == 3


class TestAllowDenyContradictions:
    def test_detects_exact_contradiction(self) -> None:
        allow = ["Bash(rm -rf)", "Bash(git log)"]
        deny = ["Bash(rm -rf)"]

        result = clean_mod.classify_rules(
            allow,
            global_rules=set(),
            current_version=None,
            deny_rules=deny,
        )

        assert len(result.allow_deny_contradictions) == 1
        assert result.allow_deny_contradictions[0] == (
            "Bash(rm -rf)",
            "Bash(rm -rf)",
        )

    def test_no_contradiction_when_different(self) -> None:
        allow = ["Bash(git log)"]
        deny = ["Bash(rm -rf)"]

        result = clean_mod.classify_rules(
            allow,
            global_rules=set(),
            current_version=None,
            deny_rules=deny,
        )

        assert result.allow_deny_contradictions == []


class TestAskShadowedByAllow:
    def test_detects_exact_shadow(self) -> None:
        allow = ["Bash(git push:*)"]
        ask = ["Bash(git push:*)"]

        result = clean_mod.classify_rules(
            allow,
            global_rules=set(),
            current_version=None,
            ask_rules=ask,
        )

        assert len(result.ask_shadowed_by_allow) == 1

    def test_detects_wildcard_shadow(self) -> None:
        allow = ["mcp__plugin_Dev10x_cli__*"]
        ask = ["mcp__plugin_Dev10x_cli__push_safe"]

        result = clean_mod.classify_rules(
            allow,
            global_rules=set(),
            current_version=None,
            ask_rules=ask,
        )

        assert len(result.ask_shadowed_by_allow) == 1

    def test_no_shadow_when_unrelated(self) -> None:
        allow = ["Bash(docker:*)"]
        ask = ["Bash(git push)"]

        result = clean_mod.classify_rules(
            allow,
            global_rules=set(),
            current_version=None,
            ask_rules=ask,
        )

        assert result.ask_shadowed_by_allow == []


class TestVerboseFormatting:
    @pytest.fixture
    def format_messages(self):
        from dev10x.skills.permission.clean_project_files import _format_messages

        return _format_messages

    def test_verbose_includes_rule_details(self, format_messages) -> None:
        result = clean_mod.RemovalResult(
            exact_duplicates=["Bash(git log:*)"],
            kept=["Bash(docker up)"],
        )

        messages = format_messages(result, verbose=True)

        verbose_output = "\n".join(messages)
        assert "Bash(git log:*)" in verbose_output

    def test_non_verbose_omits_rule_details(self, format_messages) -> None:
        result = clean_mod.RemovalResult(
            exact_duplicates=["Bash(git log:*)"],
            kept=["Bash(docker up)"],
        )

        messages = format_messages(result, verbose=False)

        output = "\n".join(messages)
        assert "1 exact duplicates" in output
        assert "Bash(git log:*)" not in output
