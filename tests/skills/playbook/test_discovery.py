"""Tests for ``dev10x.core.skills.playbook.discovery`` (GH-192, GH-546)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.domain.dev10x_paths import Dev10xConfigDir
from dev10x.core.skills.playbook import discovery
from dev10x.core.skills.playbook.discovery import (
    default_path_in,
    find_user_playbooks,
    installed_plugin_roots,
    load_plugin_default,
    plugin_default_path,
    shared_fragment_directories,
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
    """GH-1329: a skill with no dedicated default falls back to the shared one."""

    def test_returns_dedicated_path_when_it_exists(self, tmp_path: Path) -> None:
        dedicated_dir = tmp_path / "skills" / "work-on" / "references"
        dedicated_dir.mkdir(parents=True)
        (dedicated_dir / "playbook.yaml").write_text("defaults: {}")

        result = plugin_default_path(skill_key="work-on", plugin_root=tmp_path)

        assert result == dedicated_dir / "playbook.yaml"

    def test_falls_back_to_shared_playbook_default_when_dedicated_is_absent(
        self, tmp_path: Path
    ) -> None:
        """work-on's real tier-3 default is the shared skills/playbook one."""
        shared_dir = tmp_path / "skills" / "playbook" / "references"
        shared_dir.mkdir(parents=True)
        (shared_dir / "playbook.yaml").write_text("defaults: {}")

        result = plugin_default_path(skill_key="work-on", plugin_root=tmp_path)

        assert result == shared_dir / "playbook.yaml"

    def test_returns_dedicated_path_when_neither_default_exists(self, tmp_path: Path) -> None:
        """Neither default is present — report the path callers would expect."""
        result = plugin_default_path(skill_key="ghost-skill", plugin_root=tmp_path)

        assert result == tmp_path / "skills" / "ghost-skill" / "references" / "playbook.yaml"

    def test_dedicated_wins_when_both_exist(self, tmp_path: Path) -> None:
        dedicated_dir = tmp_path / "skills" / "work-on" / "references"
        dedicated_dir.mkdir(parents=True)
        (dedicated_dir / "playbook.yaml").write_text("defaults: {}")
        shared_dir = tmp_path / "skills" / "playbook" / "references"
        shared_dir.mkdir(parents=True)
        (shared_dir / "playbook.yaml").write_text("defaults: {}")

        result = plugin_default_path(skill_key="work-on", plugin_root=tmp_path)

        assert result == dedicated_dir / "playbook.yaml"

    def test_shared_default_itself_uses_dedicated_path(self, tmp_path: Path) -> None:
        """The playbook skill's own default is never redirected to itself."""
        shared_dir = tmp_path / "skills" / "playbook" / "references"
        shared_dir.mkdir(parents=True)
        (shared_dir / "playbook.yaml").write_text("defaults: {}")

        result = plugin_default_path(skill_key="playbook", plugin_root=tmp_path)

        assert result == shared_dir / "playbook.yaml"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def split_root(tmp_path: Path) -> Path:
    """A plugin root whose shared default is split into core + fragments (GH-1555)."""
    root = tmp_path / "plugin"
    _write(root / "skills/playbook/references/playbook.yaml", "version: '1'\noverrides: []\n")
    _write(
        root / "skills/work-on/references/playbook.d/coding.yaml",
        "defaults:\n  feature:\n    steps:\n    - subject: B\n    - subject: C\n",
    )
    _write(
        root / "skills/park/references/playbook.d/tasks.yaml",
        "defaults:\n  park:\n    steps:\n    - subject: P\n",
    )
    return root


class TestLoadPluginDefault:
    def test_merges_core_with_fragments_in_plugin_order(self, split_root: Path) -> None:
        document = load_plugin_default(skill_key="work-on", plugin_roots=[split_root])

        assert document == {
            "version": "1",
            "overrides": [],
            "defaults": {
                "park": {"steps": [{"subject": "P"}]},
                "feature": {"steps": [{"subject": "B"}, {"subject": "C"}]},
            },
        }

    def test_plugin_order_puts_tasks_before_coding(self, split_root: Path) -> None:
        document = load_plugin_default(skill_key="work-on", plugin_roots=[split_root])

        assert list(document["defaults"]) == ["park", "feature"]  # type: ignore[index]

    def test_dedicated_default_skips_the_merge(self, split_root: Path) -> None:
        _write(split_root / "skills/investigate/references/playbook.yaml", "defaults: {x: {}}\n")

        document = load_plugin_default(skill_key="investigate", plugin_roots=[split_root])

        assert document == {"defaults": {"x": {}}}

    def test_returns_none_without_any_default(self, tmp_path: Path) -> None:
        assert load_plugin_default(skill_key="work-on", plugin_roots=[tmp_path]) is None

    def test_searches_every_plugin_root(self, split_root: Path, tmp_path: Path) -> None:
        other = tmp_path / "other"
        _write(
            other / "skills/qa-self/references/playbook.d/qa.yaml",
            "defaults:\n  qa:\n    steps: []\n",
        )

        document = load_plugin_default(skill_key="work-on", plugin_roots=[other, split_root])

        assert list(document["defaults"]) == ["qa", "park", "feature"]  # type: ignore[index]

    def test_fragment_directories_are_listed_per_root(self, split_root: Path) -> None:
        assert shared_fragment_directories(plugin_roots=[split_root]) == [
            split_root / "skills/park/references/playbook.d",
            split_root / "skills/work-on/references/playbook.d",
        ]


class TestInstalledPluginRoots:
    """GH-1572: satellites ship playbook defaults, so readers scan them too."""

    def test_core_only_install_has_just_core(self, tmp_path: Path) -> None:
        assert installed_plugin_roots(core_root=tmp_path) == [tmp_path]

    def test_lists_a_satellite_under_a_checkout(self, tmp_path: Path) -> None:
        (tmp_path / "plugins" / "coding" / "skills").mkdir(parents=True)

        assert installed_plugin_roots(core_root=tmp_path) == [
            tmp_path,
            tmp_path / "plugins" / "coding",
        ]

    def test_repository_roots_find_the_coding_plays(self) -> None:
        from dev10x.core.subprocess_utils import get_plugin_root

        roots = installed_plugin_roots(core_root=get_plugin_root())

        assert load_plugin_default(skill_key="work-on", plugin_roots=roots)["defaults"]


class TestDefaultPathIn:
    def test_prefers_a_dedicated_default_in_a_later_root(
        self, split_root: Path, tmp_path: Path
    ) -> None:
        satellite = tmp_path / "satellite"
        dedicated = satellite / "skills/investigate/references/playbook.yaml"
        _write(dedicated, "defaults: {}\n")

        assert default_path_in(skill_key="investigate", plugin_roots=[split_root, satellite]) == (
            dedicated
        )

    def test_falls_back_to_the_shared_default(self, split_root: Path) -> None:
        assert default_path_in(skill_key="work-on", plugin_roots=[split_root]) == (
            split_root / "skills/playbook/references/playbook.yaml"
        )

    def test_names_the_expected_path_when_nothing_ships(self, tmp_path: Path) -> None:
        assert default_path_in(skill_key="ghost", plugin_roots=[tmp_path]) == (
            tmp_path / "skills/ghost/references/playbook.yaml"
        )
