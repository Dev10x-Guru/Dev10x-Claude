"""Tests for the CI context builder (GH-1321)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir
from dev10x.skills.doctor.context import build_context


@pytest.fixture
def claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "claude-home"
    home.mkdir()
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
    ClaudeDir.reset_cache()
    yield home
    ClaudeDir.reset_cache()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    return root


def touch(path: Path) -> Path:
    path.write_text("{}", encoding="utf-8")
    return path


class TestSettingsPaths:
    def test_user_scope_settings_are_included(self, claude_home: Path, project: Path) -> None:
        touch(claude_home / "settings.json")

        context = build_context(project_root=project)

        assert claude_home / "settings.json" in context.settings_paths

    def test_project_scope_settings_are_included(self, claude_home: Path, project: Path) -> None:
        touch(project / ".claude" / "settings.local.json")

        context = build_context(project_root=project)

        assert project / ".claude" / "settings.local.json" in context.settings_paths

    def test_absent_files_are_not_listed(self, claude_home: Path, project: Path) -> None:
        # A phantom entry would send retired_session_yaml probing a
        # directory nobody has, and makes the payload unreadable.
        assert build_context(project_root=project).settings_paths == ()

    def test_defaults_to_the_working_directory(
        self,
        claude_home: Path,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        touch(project / ".claude" / "settings.json")
        monkeypatch.chdir(project)

        assert project / ".claude" / "settings.json" in build_context().settings_paths


class TestOtherRoots:
    def test_memory_root_is_reported_when_present(self, claude_home: Path, project: Path) -> None:
        (claude_home / "memory").mkdir()

        assert build_context(project_root=project).memory_roots == (claude_home / "memory",)

    def test_memory_root_is_empty_when_absent(self, claude_home: Path, project: Path) -> None:
        assert build_context(project_root=project).memory_roots == ()

    def test_plugin_cache_is_reported_when_present(self, claude_home: Path, project: Path) -> None:
        cache = claude_home / "plugins" / "cache"
        cache.mkdir(parents=True)

        assert build_context(project_root=project).plugin_cache_root == cache

    def test_plugin_cache_is_none_when_absent(self, claude_home: Path, project: Path) -> None:
        assert build_context(project_root=project).plugin_cache_root is None
