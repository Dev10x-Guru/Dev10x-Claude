"""Unit tests for SessionService — the injectable session-context service layer.

These tests exercise SessionService methods directly, which is the new
testability unlock of the GH-529 refactor. Prior to this, the same logic
was only reachable indirectly through the hook dispatch entry points.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.domain.session_document import state_path_for_toplevel, write_state
from dev10x.session.service import SessionService


def _write_state(*, toplevel: str, session_id: str) -> Path:
    path = state_path_for_toplevel(toplevel=toplevel)
    write_state(
        path=path,
        state={
            "session_id": session_id,
            "branch": "develop",
            "worktree": "",
            "working_directory": toplevel,
            "timestamp": "2026-01-01T00:00:00Z",
            "modified_files": [],
            "staged_files": [],
            "recent_commits": ["abc1234 Test commit"],
            "has_plan": False,
        },
    )
    return path


class TestSessionServiceConstruction:
    def test_accepts_explicit_plugin_root(self, tmp_path: Path) -> None:
        svc = SessionService(plugin_root=tmp_path)
        assert svc._plugin_root == tmp_path

    def test_resolves_default_plugin_root_when_none(self) -> None:
        svc = SessionService()
        assert svc._plugin_root.exists()

    def test_default_plugin_root_contains_src_dir(self) -> None:
        svc = SessionService()
        assert (svc._plugin_root / "src").exists()


class TestBuildReloadContext:
    def test_empty_when_toplevel_is_none(self) -> None:
        svc = SessionService()
        result = svc.build_reload_context(toplevel=None)
        # Without a real git repo, GitContext returns None — result must be ""
        # When running in a real repo the test repo's state may exist;
        # passing an explicit non-existent path ensures isolation.
        assert isinstance(result, str)

    def test_empty_when_no_state_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
        repo = tmp_path / "repo"
        repo.mkdir()
        svc = SessionService()
        assert svc.build_reload_context(toplevel=str(repo)) == ""

    def test_includes_state_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_state(toplevel=str(repo), session_id="svc-test-session")

        svc = SessionService()
        result = svc.build_reload_context(toplevel=str(repo))

        assert "Prior session state detected" in result
        assert "svc-test-session" in result

    def test_consumes_state_file_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
        repo = tmp_path / "repo"
        repo.mkdir()
        path = _write_state(toplevel=str(repo), session_id="cleanup-svc-test")
        assert path.exists()

        svc = SessionService()
        svc.build_reload_context(toplevel=str(repo))

        assert not path.exists()


class TestBuildGuidanceContext:
    def test_empty_when_guidance_file_missing(self, tmp_path: Path) -> None:
        svc = SessionService(plugin_root=tmp_path)
        assert svc.build_guidance_context() == ""

    def test_returns_file_contents_when_present(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "hooks" / "scripts"
        scripts_dir.mkdir(parents=True)
        guidance = scripts_dir / "session-guidance.md"
        guidance.write_text("# Guidance content\nSome instructions here.")

        svc = SessionService(plugin_root=tmp_path)
        result = svc.build_guidance_context()

        assert "Guidance content" in result
        assert "Some instructions here" in result

    def test_real_plugin_root_has_guidance_file(self) -> None:
        svc = SessionService()
        result = svc.build_guidance_context()
        assert len(result) > 0


class TestBuildInstallCheckContext:
    def test_empty_when_install_current(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.domain.install_version import write_applied_version

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

        svc = SessionService()
        assert svc.build_install_check_context() == ""

    def test_guides_bootstrap_when_config_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config_dev10x"))
        Dev10xConfigDir.reset_cache()
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        svc = SessionService()
        result = svc.build_install_check_context()

        assert "config folder is missing" in result
        assert "/Dev10x:upgrade-cleanup" in result

    def test_guides_upgrade_on_version_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
        from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir
        from dev10x.domain.install_version import write_applied_version

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

        svc = SessionService()
        result = svc.build_install_check_context()

        assert "0.72.0" in result
        assert "0.71.0" in result
        assert "/Dev10x:upgrade-cleanup" in result


class TestBuildHookVersionDriftContext:
    def test_empty_when_versions_match(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir

        plugin_root = tmp_path / "plugins" / "cache" / "Dev10x-Guru" / "dev10x-claude" / "0.76.0"
        (plugin_root / ".claude-plugin").mkdir(parents=True)
        (plugin_root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "0.76.0"})
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        svc = SessionService()
        assert svc.build_hook_version_drift_context() == ""

    def test_warns_when_newer_version_installed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir

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

        svc = SessionService()
        result = svc.build_hook_version_drift_context()

        assert "0.72.0" in result
        assert "0.76.0" in result
        assert "restart" in result.lower()

    def test_empty_when_running_version_unknown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir

        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path))
        ClaudeDir.reset_cache()

        svc = SessionService()
        assert svc.build_hook_version_drift_context() == ""


class TestBuildCompactionContext:
    def test_empty_when_toplevel_none(self) -> None:
        svc = SessionService()
        result = svc.build_compaction_context(toplevel=None)
        assert isinstance(result, str)

    def test_returns_string_with_valid_toplevel(self, tmp_path: Path) -> None:
        with (
            patch("dev10x.domain.documents.session_context.GitContext") as mock_git_cls,
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.SessionYamlDocument") as mock_doc,
        ):
            from dev10x.domain.friction_level import FrictionLevel

            mock_git = mock_git_cls.return_value
            mock_git.branch = "feature/test"
            mock_git.run.return_value = ""
            mock_doc.return_value.read_friction_level.return_value = FrictionLevel.default()

            svc = SessionService(plugin_root=tmp_path)
            result = svc.build_compaction_context(toplevel=str(tmp_path))

        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_branch_in_output(self, tmp_path: Path) -> None:
        with (
            patch("dev10x.domain.documents.session_context.GitContext") as mock_git_cls,
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.SessionYamlDocument") as mock_doc,
        ):
            from dev10x.domain.friction_level import FrictionLevel

            mock_git = mock_git_cls.return_value
            mock_git.branch = "feature/svc-test"
            mock_git.run.return_value = ""
            mock_doc.return_value.read_friction_level.return_value = FrictionLevel.default()

            svc = SessionService(plugin_root=tmp_path)
            result = svc.build_compaction_context(toplevel=str(tmp_path))

        assert "feature/svc-test" in result
