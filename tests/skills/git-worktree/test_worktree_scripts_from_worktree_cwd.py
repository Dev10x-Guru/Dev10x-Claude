"""GH-960 regression: exercise both git-worktree scripts from a CWD that
is itself a linked worktree, not just from the main checkout.

Prior to the fix, ``next-worktree-name.sh`` resolved the worktrees
parent via ``git rev-parse --show-toplevel``, which returns the
*current* worktree's own path when invoked from inside one — computing
a bogus nested ``<worktree>/.worktrees`` directory instead of the
sibling directory next to the main repo. ``create-worktree.sh`` had no
slot for a base ref at all, so callers wanting to start a new worktree
branch from a specific ref had nothing but the (misused) repo-root
positional to abuse.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "skills" / "git-worktree" / "scripts"


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _run_script(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPTS_DIR / script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    """A bare-bones main checkout named ``proj`` with one commit."""
    repo = tmp_path / "proj"
    repo.mkdir()
    _git("init", "-q", "-b", "develop", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    _git("config", "commit.gpgsign", "false", cwd=repo)
    (repo / "README.md").write_text("hello\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)
    return repo


@pytest.fixture
def linked_worktree(main_repo: Path, tmp_path: Path) -> Path:
    """A linked worktree sibling to ``main_repo``, e.g. ``.worktrees/proj-1``."""
    worktrees_dir = tmp_path / ".worktrees"
    worktree_path = worktrees_dir / "proj-1"
    _git(
        "worktree",
        "add",
        str(worktree_path),
        "-b",
        "existing-worktree-branch",
        cwd=main_repo,
    )
    return worktree_path


class TestNextWorktreeNameFromLinkedWorktree:
    def test_resolves_parent_next_to_main_repo_not_nested_under_worktree(
        self,
        main_repo: Path,
        linked_worktree: Path,
    ) -> None:
        result = _run_script("next-worktree-name.sh", cwd=linked_worktree)

        assert result.returncode == 0, result.stderr
        computed_path = result.stdout.strip()

        # Correct: sibling to the main repo → tmp_path/.worktrees/proj-2
        assert computed_path == str(main_repo.parent / ".worktrees" / "proj-2")
        # Regression guard: must NOT be nested under the worktree itself.
        assert ".worktrees/.worktrees" not in computed_path

    def test_computed_from_main_repo_matches_from_worktree(
        self,
        main_repo: Path,
        linked_worktree: Path,
    ) -> None:
        from_main = _run_script("next-worktree-name.sh", cwd=main_repo).stdout.strip()
        from_worktree = _run_script("next-worktree-name.sh", cwd=linked_worktree).stdout.strip()

        assert from_main == from_worktree


class TestCreateWorktreeFromLinkedWorktree:
    def test_creates_sibling_worktree_with_base_ref(
        self,
        main_repo: Path,
        linked_worktree: Path,
        tmp_path: Path,
    ) -> None:
        new_worktree_path = tmp_path / ".worktrees" / "proj-2"

        result = _run_script(
            "create-worktree.sh",
            str(new_worktree_path),
            "janusz/GH-960/slug",
            "develop",
            cwd=linked_worktree,
        )

        assert result.returncode == 0, result.stderr
        assert new_worktree_path.exists()
        assert (new_worktree_path / "README.md").exists()

        branch_output = _git("branch", "--show-current", cwd=new_worktree_path)
        assert branch_output.strip() == "janusz/GH-960/slug"

    def test_rejects_missing_branch_name_with_usage_message(
        self,
        linked_worktree: Path,
        tmp_path: Path,
    ) -> None:
        result = _run_script(
            "create-worktree.sh",
            str(tmp_path / ".worktrees" / "proj-3"),
            cwd=linked_worktree,
        )

        assert result.returncode != 0
        assert "Usage: create-worktree.sh" in result.stderr
