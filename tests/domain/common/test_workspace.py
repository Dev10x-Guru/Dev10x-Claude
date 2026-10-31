"""Tests for the Workspace value object (PAP-3, GH-800)."""

from __future__ import annotations

import pytest
from dev10x.domain.common.workspace import Workspace


class TestWorkspace:
    def test_main_checkout_is_not_a_worktree(self) -> None:
        workspace = Workspace(root="/work/dx/Dev10x-Claude")
        assert workspace.is_worktree is False
        assert workspace.worktree_name == ""

    def test_worktree_root_is_detected_and_named(self) -> None:
        workspace = Workspace(root="/work/dx/.worktrees/dx-zebra-4")
        assert workspace.is_worktree is True
        assert workspace.worktree_name == "dx-zebra-4"

    def test_worktree_name_ignores_nested_segments(self) -> None:
        workspace = Workspace(root="/work/dx/.worktrees/dx-zebra-4/src/pkg")
        assert workspace.worktree_name == "dx-zebra-4"

    @pytest.mark.parametrize(
        ("root", "name"),
        [
            ("/work/.herdr/worktrees/Dev10x-Claude/janusz-milestone-74", "janusz-milestone-74"),
            ("/home/u/.herdr/worktrees/tt-pos/tt-pos-3", "tt-pos-3"),
            ("/home/u/.herdr/worktrees/tt-pos/tt-pos-3/src/app", "tt-pos-3"),
        ],
    )
    def test_herdr_worktree_is_detected_and_named(self, root: str, name: str) -> None:
        """GH-1666: herdr worktrees carry no `/.worktrees/` segment."""
        workspace = Workspace(root=root)
        assert workspace.is_worktree is True
        assert workspace.worktree_name == name

    def test_herdr_root_itself_is_not_a_worktree(self) -> None:
        assert Workspace(root="/work/.herdr/worktrees/Dev10x-Claude").is_worktree is False

    def test_from_config_collects_string_directories(self) -> None:
        config = {"workspace_directories": ["/tmp/Dev10x", "~/.claude/memory", 42, None]}
        workspace = Workspace.from_config(root="/work/repo", config=config)
        assert workspace.additional_directories == ("/tmp/Dev10x", "~/.claude/memory")

    @pytest.mark.parametrize("value", [None, "oops", {"a": 1}])
    def test_from_config_non_list_yields_no_directories(self, value: object) -> None:
        workspace = Workspace.from_config(
            root="/work/repo", config={"workspace_directories": value}
        )
        assert workspace.additional_directories == ()

    def test_is_frozen(self) -> None:
        workspace = Workspace(root="/work/repo")
        with pytest.raises(AttributeError):
            workspace.root = "/elsewhere"  # type: ignore[misc]
