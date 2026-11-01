"""Tests for dev10x.domain.linked_worktree (GH-1493)."""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.domain.linked_worktree import main_checkout


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "wt"
    path.mkdir()
    return path


@pytest.mark.parametrize(
    "gitdir",
    [
        "/work/repo/.git/worktrees/wt",
        "../repo/.git/worktrees/wt",
    ],
)
def test_linked_worktree_resolves_to_main_checkout(worktree: Path, gitdir: str) -> None:
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

    resolved = main_checkout(worktree)

    assert resolved is not None
    assert resolved.resolve() == (worktree / gitdir).resolve().parent.parent.parent


def test_relative_gitdir_is_returned_normalised(tmp_path: Path, worktree: Path) -> None:
    # GH-1733 (b): callers compare this path against a checkout root, so a
    # surviving `..` segment would miss the match even though it names the
    # same directory. The result must already be normalised.
    (worktree / ".git").write_text("gitdir: ../repo/.git/worktrees/wt\n")

    resolved = main_checkout(worktree)

    assert resolved == (tmp_path / "repo").resolve()
    assert ".." not in resolved.parts


def test_main_checkout_with_git_directory_is_not_linked(worktree: Path) -> None:
    (worktree / ".git").mkdir()

    assert main_checkout(worktree) is None


def test_missing_git_entry_is_not_linked(worktree: Path) -> None:
    assert main_checkout(worktree) is None


@pytest.mark.parametrize(
    "content",
    [
        "not a gitdir pointer",
        "gitdir: /work/repo/.git/modules/sub",
    ],
)
def test_non_worktree_pointer_is_not_linked(worktree: Path, content: str) -> None:
    (worktree / ".git").write_text(content)

    assert main_checkout(worktree) is None


def test_unreadable_git_file_is_not_linked(worktree: Path) -> None:
    git_file = worktree / ".git"
    git_file.write_text("gitdir: /work/repo/.git/worktrees/wt")
    git_file.chmod(0o000)

    try:
        assert main_checkout(worktree) is None
    finally:
        git_file.chmod(0o644)
