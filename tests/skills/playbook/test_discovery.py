"""Tests for ``dev10x.skills.playbook.discovery`` (GH-192, GH-546)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.playbook import discovery
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

    def test_finds_legacy_global_overrides(self, tmp_path: Path) -> None:
        """The retired memory tree stays readable — migration only copies once."""
        home = tmp_path / "home"
        global_dir = home / ".claude" / "memory" / "Dev10x" / "playbooks"
        global_dir.mkdir(parents=True)
        (global_dir / "release-notes.yaml").write_text("overrides: []")
        found = find_user_playbooks(project_root=tmp_path, home=home)
        assert len(found) == 1
        assert found[0].skill_key == "release-notes"
        assert found[0].scope == "global"

    def test_default_root_uses_effective_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GH-546: a bound worktree CWD wins over the process CWD."""
        project_dir = tmp_path / ".claude" / "Dev10x" / "playbooks"
        project_dir.mkdir(parents=True)
        (project_dir / "work-on.yaml").write_text("overrides: []")
        monkeypatch.setattr(discovery, "effective_cwd", lambda: str(tmp_path))
        found = find_user_playbooks(home=tmp_path / "home")
        assert [p.skill_key for p in found] == ["work-on"]
        assert found[0].scope == "project"

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


class TestXdgGlobalOverrides:
    """GH-1045: the canonical tier-2 home was never searched.

    GH-941 rehomed user config to ``~/.config/Dev10x``, but this reader kept
    pointing only at the retired memory tree — so a playbook written to the
    documented location was silently ignored.
    """

    def test_finds_overrides_in_the_xdg_playbooks_dir(self, tmp_path: Path) -> None:
        global_dir = Dev10xConfigDir.playbooks_dir()
        global_dir.mkdir(parents=True, exist_ok=True)
        (global_dir / "release-notes.yaml").write_text("overrides: []")

        found = find_user_playbooks(project_root=tmp_path, home=tmp_path / "home")

        assert len(found) == 1
        assert found[0].skill_key == "release-notes"
        assert found[0].scope == "global"
        assert found[0].path.parent == global_dir

    def test_xdg_shadows_the_legacy_copy_of_the_same_skill(self, tmp_path: Path) -> None:
        """One entry per skill — a user mid-migration must not see duplicates."""
        home = tmp_path / "home"
        legacy_dir = home / ".claude" / "memory" / "Dev10x" / "playbooks"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "work-on.yaml").write_text("overrides: []")
        xdg_dir = Dev10xConfigDir.playbooks_dir()
        xdg_dir.mkdir(parents=True, exist_ok=True)
        (xdg_dir / "work-on.yaml").write_text("overrides: []")

        found = find_user_playbooks(project_root=tmp_path, home=home)

        assert [p.path.parent for p in found] == [xdg_dir]

    def test_both_locations_are_searched_for_distinct_skills(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        legacy_dir = home / ".claude" / "memory" / "Dev10x" / "playbooks"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "release-notes.yaml").write_text("overrides: []")
        xdg_dir = Dev10xConfigDir.playbooks_dir()
        xdg_dir.mkdir(parents=True, exist_ok=True)
        (xdg_dir / "work-on.yaml").write_text("overrides: []")

        found = find_user_playbooks(project_root=tmp_path, home=home)

        assert sorted(p.skill_key for p in found) == ["release-notes", "work-on"]


class TestPluginDefaultPath:
    def test_builds_expected_path(self, tmp_path: Path) -> None:
        result = plugin_default_path(skill_key="work-on", plugin_root=tmp_path)
        assert result == tmp_path / "skills" / "work-on" / "references" / "playbook.yaml"
