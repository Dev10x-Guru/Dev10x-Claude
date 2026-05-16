"""Tests for ``dev10x.skills.playbook.discovery`` (GH-192)."""

from __future__ import annotations

from pathlib import Path

from dev10x.skills.playbook.discovery import (
    find_user_playbooks,
    plugin_default_path,
)


class TestFindUserPlaybooks:
    def test_returns_empty_when_no_overrides_exist(self, tmp_path: Path) -> None:
        assert find_user_playbooks(project_root=tmp_path, home=tmp_path / "home") == []

    def test_finds_project_local_overrides(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".claude" / "Dev10x" / "playbooks"
        project_dir.mkdir(parents=True)
        (project_dir / "work-on.yaml").write_text("overrides: []")
        found = find_user_playbooks(project_root=tmp_path, home=tmp_path / "home")
        assert len(found) == 1
        assert found[0].skill_key == "work-on"
        assert found[0].scope == "project"

    def test_finds_global_overrides(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        global_dir = home / ".claude" / "memory" / "Dev10x" / "playbooks"
        global_dir.mkdir(parents=True)
        (global_dir / "release-notes.yaml").write_text("overrides: []")
        found = find_user_playbooks(project_root=tmp_path, home=home)
        assert len(found) == 1
        assert found[0].skill_key == "release-notes"
        assert found[0].scope == "global"

    def test_returns_both_scopes(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        project_dir = tmp_path / ".claude" / "Dev10x" / "playbooks"
        global_dir = home / ".claude" / "memory" / "Dev10x" / "playbooks"
        project_dir.mkdir(parents=True)
        global_dir.mkdir(parents=True)
        (project_dir / "work-on.yaml").write_text("overrides: []")
        (global_dir / "work-on.yaml").write_text("overrides: []")
        found = find_user_playbooks(project_root=tmp_path, home=home)
        scopes = sorted(p.scope for p in found)
        assert scopes == ["global", "project"]


class TestPluginDefaultPath:
    def test_builds_expected_path(self, tmp_path: Path) -> None:
        result = plugin_default_path(skill_key="work-on", plugin_root=tmp_path)
        assert result == tmp_path / "skills" / "work-on" / "references" / "playbook.yaml"
