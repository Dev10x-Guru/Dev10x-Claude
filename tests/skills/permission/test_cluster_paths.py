"""Tests for path clustering (GH-115)."""

from __future__ import annotations

import os

import pytest

mod = pytest.importorskip(
    "dev10x.skills.permission.cluster_paths",
    reason="dev10x not installed",
)


class TestFindCommonAncestor:
    def test_two_sibling_paths_share_parent(self) -> None:
        result = mod.find_common_ancestor(
            paths=["/home/user/notes/a.md", "/home/user/notes/b.md"],
        )
        assert result.endswith("notes") or result.endswith("user")

    def test_empty_list_returns_empty_string(self) -> None:
        assert mod.find_common_ancestor(paths=[]) == ""

    def test_caps_at_depth_below_home(self) -> None:
        home = os.path.expanduser("~")
        deep = f"{home}/projects/foo/bar/baz/qux.txt"
        result = mod.find_common_ancestor(paths=[deep], depth=2)
        assert result.startswith(home)
        assert result.count(os.sep) <= home.count(os.sep) + 2


class TestClusterPaths:
    def test_skips_tmp_paths(self) -> None:
        clusters = mod.cluster_paths(paths=["/tmp/foo/bar.txt"])
        assert clusters == []

    def test_skips_project_worktree_paths(self) -> None:
        clusters = mod.cluster_paths(
            paths=["/work/dx/.worktrees/abc/src/file.py"],
        )
        assert clusters == []

    def test_groups_user_paths_by_ancestor(self) -> None:
        home = os.path.expanduser("~")
        clusters = mod.cluster_paths(
            paths=[
                f"{home}/notes/a.md",
                f"{home}/notes/b.md",
            ],
            depth=2,
        )
        assert len(clusters) >= 1


class TestProposePatch:
    def test_emits_full_coverage_bundle(self) -> None:
        cluster = mod.PathCluster(
            ancestor="/home/user/vault",
            paths=["/home/user/vault/a.md"],
        )
        patch = mod.propose_patch(cluster=cluster)

        assert patch.additional_directory == "/home/user/vault"
        assert patch.placement == "project"
        assert "Read(/home/user/vault/**)" in patch.rules
        assert "Write(/home/user/vault/**)" in patch.rules
        assert "Edit(/home/user/vault/**)" in patch.rules
        assert "Bash(find /home/user/vault:*)" in patch.rules
        assert "Bash(ls /home/user/vault:*)" in patch.rules
        assert "Bash(grep -r /home/user/vault:*)" in patch.rules

    def test_real_home_placement_is_user_level(self) -> None:
        home = os.path.expanduser("~")
        cluster = mod.PathCluster(
            ancestor=f"{home}/vault",
            paths=[f"{home}/vault/a.md"],
        )
        patch = mod.propose_patch(cluster=cluster)
        assert patch.placement == "user"
