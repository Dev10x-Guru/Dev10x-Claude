"""Tests for dev10x hook session {tmpdir,guidance,git-aliases,migrate-permissions}."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.cli import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestSessionTmpdir:
    def test_creates_session_directory(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "tmpdir"],
            input=json.dumps({"session_id": "test-session-abc"}),
        )

        assert result.exit_code == 0
        assert Path("/tmp/Dev10x/test-session-abc").exists()

    def test_exits_silently_without_session_id(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "tmpdir"],
            input=json.dumps({}),
        )

        assert result.exit_code == 0
        assert result.output == ""

    def test_exits_silently_on_invalid_json(self) -> None:
        from dev10x.hooks.session import session_tmpdir

        original_stdin = sys.stdin
        sys.stdin = io.StringIO("{not valid json}")
        try:
            with pytest.raises(SystemExit) as exc_info:
                session_tmpdir()
        finally:
            sys.stdin = original_stdin

        assert exc_info.value.code == 0

    def test_installs_mktmp_to_bin(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "tmpdir"],
            input=json.dumps({"session_id": "test-mktmp-install"}),
        )

        assert result.exit_code == 0
        assert Path("/tmp/Dev10x/bin/mktmp.sh").exists()
        assert Path("/tmp/Dev10x/bin/mktmp.sh").stat().st_mode & 0o111


class TestSessionGuidance:
    def test_outputs_valid_json(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "guidance"],
            input="{}",
        )

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert "hookSpecificOutput" in output
        assert "additionalContext" in output["hookSpecificOutput"]

    def test_output_contains_guidance_content(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "guidance"],
            input="{}",
        )

        output = json.loads(result.output)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert len(context) > 0

    def test_exits_silently_when_guidance_file_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.session_dispatch as mod

        fake_root = Path("/tmp/nonexistent-plugin-root-xyz")
        monkeypatch.setattr(mod, "_plugin_root", lambda: fake_root)

        with pytest.raises(SystemExit) as exc_info:
            mod.session_guidance()
        assert exc_info.value.code == 0


class TestSessionInstallCheck:
    def test_silent_when_install_current(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.domain.install_version import write_applied_version
        from dev10x.hooks.session_dispatch import build_install_check_context

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
        Dev10xConfigDir.reset_cache()
        Dev10xConfigDir.home().mkdir(parents=True)
        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.72.0"})
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        write_applied_version(plugin_version="0.72.0")

        assert build_install_check_context() == ""

    def test_guides_bootstrap_when_config_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.hooks.session_dispatch import build_install_check_context

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
        Dev10xConfigDir.reset_cache()
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        ctx = build_install_check_context()
        assert "config folder is missing" in ctx
        assert "/Dev10x:upgrade-cleanup" in ctx

    def test_guides_upgrade_on_version_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.domain.install_version import write_applied_version
        from dev10x.hooks.session_dispatch import build_install_check_context

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
        Dev10xConfigDir.reset_cache()
        Dev10xConfigDir.home().mkdir(parents=True)
        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.72.0"})
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        write_applied_version(plugin_version="0.71.0")

        ctx = build_install_check_context()
        assert "0.72.0" in ctx
        assert "0.71.0" in ctx
        assert "/Dev10x:upgrade-cleanup" in ctx

    def test_session_install_check_emits_envelope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.hooks.session_dispatch import session_install_check

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
        Dev10xConfigDir.reset_cache()
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        session_install_check()
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "config folder" in payload["hookSpecificOutput"]["additionalContext"]

    def test_session_install_check_silent_when_current(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
        from dev10x.domain.install_version import write_applied_version
        from dev10x.hooks.session_dispatch import session_install_check

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.dev10x_config_dir().mkdir(parents=True)
        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.72.0"})
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        write_applied_version(plugin_version="0.72.0")

        with pytest.raises(SystemExit) as exc_info:
            session_install_check()
        assert exc_info.value.code == 0
        assert capsys.readouterr().out == ""

    def test_guides_upgrade_on_fresh_bootstrap_no_version_recorded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config dir present but version.yml absent — needs_upgrade fires with 'never applied'."""
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.hooks.session_dispatch import build_install_check_context

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
        Dev10xConfigDir.reset_cache()
        Dev10xConfigDir.home().mkdir(parents=True)

        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.72.0"})
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))

        ctx = build_install_check_context()

        assert "0.72.0" in ctx
        assert "never applied" in ctx
        assert "/Dev10x:upgrade-cleanup" in ctx

    def test_silent_when_plugin_version_unreadable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Plugin manifest missing/unreadable — needs_upgrade short-circuits to False."""
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.domain.install_version import write_applied_version
        from dev10x.hooks.session_dispatch import build_install_check_context

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
        Dev10xConfigDir.reset_cache()
        Dev10xConfigDir.home().mkdir(parents=True)
        write_applied_version(plugin_version="0.71.0")

        monkeypatch.setattr(
            "dev10x.domain.install_version.read_plugin_version",
            lambda **kwargs: None,
        )

        assert build_install_check_context() == ""


class TestSessionHookVersionDrift:
    """GH-407: Running-hook version drift detector."""

    def test_silent_when_versions_match(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
        from dev10x.hooks.session_dispatch import build_hook_version_drift_context

        plugin_root = tmp_path / "plugins" / "cache" / "Dev10x-Guru" / "dev10x-claude" / "0.76.0"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.76.0"})
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        assert build_hook_version_drift_context() == ""

    def test_warns_when_newer_version_installed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
        from dev10x.hooks.session_dispatch import build_hook_version_drift_context

        cache_base = tmp_path / "plugins" / "cache" / "Dev10x-Guru" / "dev10x-claude"
        old_root = cache_base / "0.72.0"
        new_root = cache_base / "0.76.0"
        for root in (old_root, new_root):
            (root / ".claude-plugin").mkdir(parents=True)
            ver = root.name
            (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": ver}))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(old_root))
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        ctx = build_hook_version_drift_context()
        assert "0.72.0" in ctx
        assert "0.76.0" in ctx
        assert "restart" in ctx.lower()
        assert "/Dev10x:upgrade-cleanup" in ctx

    def test_silent_when_running_version_unknown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
        from dev10x.hooks.session_dispatch import build_hook_version_drift_context

        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        assert build_hook_version_drift_context() == ""

    def test_silent_when_cache_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
        from dev10x.hooks.session_dispatch import build_hook_version_drift_context

        plugin_root = tmp_path / "plugin"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.72.0"})
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        assert build_hook_version_drift_context() == ""

    def test_message_distinct_from_settings_staleness(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Drift message must not reference settings/upgrade state — only
        running-hook vs installed-version mismatch."""
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
        from dev10x.hooks.session_dispatch import build_hook_version_drift_context

        cache_base = tmp_path / "plugins" / "cache" / "Dev10x-Guru" / "dev10x-claude"
        old_root = cache_base / "0.72.0"
        new_root = cache_base / "0.76.0"
        for root in (old_root, new_root):
            (root / ".claude-plugin").mkdir(parents=True)
            ver = root.name
            (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": ver}))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(old_root))
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        ctx = build_hook_version_drift_context()
        assert "hooks running" in ctx
        assert "installed on disk" in ctx
        assert "upgrade-cleanup was last run" not in ctx


class TestSessionGitAliases:
    def test_outputs_alias_status(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "git-aliases"],
            input="{}",
        )

        assert result.exit_code == 0
        assert len(result.output) > 0

    def test_output_mentions_aliases(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "git-aliases"],
            input="{}",
        )

        assert "Git aliases" in result.output

    def test_reports_all_missing_when_no_aliases_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.session_place as mod

        monkeypatch.setattr(mod, "_run_git", lambda *args: "")

        captured = io.StringIO()
        sys.stdout = captured
        try:
            mod.session_git_aliases()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        assert "Git aliases missing" in output
        assert "git-alias-setup" in output

    def test_reports_partial_aliases_in_missing_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.session_place as mod

        call_count = 0

        def fake_run_git(*args: str) -> str:
            nonlocal call_count
            call_count += 1
            return "value" if call_count == 1 else ""

        monkeypatch.setattr(mod, "_run_git", fake_run_git)

        captured = io.StringIO()
        sys.stdout = captured
        try:
            mod.session_git_aliases()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        assert "Git aliases missing" in output
        assert "Git aliases available" in output


class TestBuildMigrationReplacements:
    def test_builds_replacements_for_sibling_versions(self, tmp_path: Path) -> None:
        from dev10x.hooks.session import _build_migration_replacements

        plugin_root = tmp_path / "1.0.0"
        old_version = tmp_path / "0.9.0"
        plugin_root.mkdir()
        old_version.mkdir()

        replacements = _build_migration_replacements(
            plugin_root=plugin_root,
            home=str(tmp_path),
        )

        assert len(replacements) > 0
        assert any(str(old_version) in old for old, _ in replacements)

    def test_returns_empty_on_oserror(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.hooks.session import _build_migration_replacements

        plugin_root = tmp_path / "current"
        plugin_root.mkdir()

        monkeypatch.setattr(
            Path, "iterdir", lambda self: (_ for _ in ()).throw(OSError("no access"))
        )

        replacements = _build_migration_replacements(
            plugin_root=plugin_root,
            home=str(tmp_path),
        )

        assert replacements == []


class TestMigrateRules:
    def test_replaces_old_path_in_rule(self, tmp_path: Path) -> None:
        from dev10x.hooks.session import _migrate_rules

        old = str(tmp_path / "old") + "/"
        new = str(tmp_path / "new") + "/"
        rules = [f"Bash({old}scripts/:*)"]
        result, count = _migrate_rules(rules=rules, replacements=[(old, new)])

        assert count == 1
        assert new in result[0]

    def test_preserves_unmatched_rules(self) -> None:
        from dev10x.hooks.session import _migrate_rules

        rules = ["Read", "Write", "Bash(~/.claude/tools/:*)"]
        result, count = _migrate_rules(rules=rules, replacements=[("/old/", "/new/")])

        assert count == 0
        assert result == rules


class TestDeduplicateRules:
    def test_removes_duplicates(self) -> None:
        from dev10x.hooks.session import _deduplicate_rules

        rules = ["rule-a", "rule-b", "rule-a", "rule-c"]
        result = _deduplicate_rules(rules=rules)

        assert result == ["rule-a", "rule-b", "rule-c"]

    def test_preserves_order(self) -> None:
        from dev10x.hooks.session import _deduplicate_rules

        rules = ["c", "a", "b", "a"]
        result = _deduplicate_rules(rules=rules)

        assert result == ["c", "a", "b"]


class TestSessionMigratePermissions:
    def test_exits_silently_for_non_cache_install(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["hook", "session", "migrate-permissions"],
            input="{}",
        )

        assert result.exit_code == 0

    def test_migrates_settings_file_for_cache_install(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import dev10x.hooks.session as mod
        import dev10x.hooks.session_dispatch as dispatch_mod

        fake_plugin_root = tmp_path / "plugins" / "cache" / "Dev10x" / "1.0.0"
        fake_old_version = tmp_path / "plugins" / "cache" / "Dev10x" / "0.9.0"
        fake_plugin_root.mkdir(parents=True)
        fake_old_version.mkdir(parents=True)

        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_file = settings_dir / "settings.json"
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [f"Bash({fake_old_version}/scripts/:*)"],
                    }
                }
            )
        )

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(dispatch_mod, "_plugin_root", lambda: fake_plugin_root)

        mod.session_migrate_permissions()

        updated = json.loads(settings_file.read_text())
        allow_rules = updated["permissions"]["allow"]
        assert any(str(fake_plugin_root) in r for r in allow_rules)
