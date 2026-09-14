"""GH-1299: the worktree post-checkout hook must not copy tracked files.

A fresh worktree kept arriving with uncommitted deletions in tracked
``.claude/rules/*.md``. ``git worktree add`` materializes those files at
the new worktree's own commit, and the hook then rsynced the *source
checkout's* copy over them — so whenever that checkout sat on an older
commit or another branch, the new worktree's tracked content was
silently reverted.

These tests drive the real templates end-to-end against a throwaway
repo, because the defect lives in the shell copy logic rather than in
anything importable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

NEW_WORKTREE_SHA = "0" * 40

STALE_RULE = "the source checkout's older copy of this rule\n"
CURRENT_RULE = "current\n"

TEMPLATES = [
    "post-checkout-python-uv.sh",
    "post-checkout-node.sh",
    "post-checkout-node-husky.sh",
]


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture
def stub_bin(tmp_path: Path) -> Path:
    """Neutralize the hook's post-copy dependency install.

    The templates end by shelling out to uv/yarn/pnpm/npm and the dev10x
    CLI. None of that is under test, and letting a real ``uv sync`` run
    would make this a network test.
    """
    stubs = tmp_path / "stub-bin"
    stubs.mkdir()
    for tool in ("uv", "uvx", "dev10x", "yarn", "pnpm", "npm", "npx"):
        stub = stubs / tool
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    return stubs


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A repo whose working tree sits on OLD content for a tracked file.

    ``main`` holds v1 and stays checked out here; ``feature`` holds v2 and
    is what the new worktree will check out. That gap is the whole bug.
    """
    root = tmp_path / "origin"
    (root / ".claude" / "rules").mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")

    (root / ".gitignore").write_text(".claude/settings.local.json\n")
    # The two versions differ in LENGTH on purpose: rsync's quick check
    # skips a transfer when size and mtime both match, and two same-sized
    # files written in the same second would make this test pass against
    # the unfixed hook.
    (root / ".claude" / "rules" / "keep.md").write_text(STALE_RULE)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "stale")

    _git(root, "checkout", "-b", "feature")
    (root / ".claude" / "rules" / "keep.md").write_text(CURRENT_RULE)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "current")
    _git(root, "checkout", "main")

    # Gitignored local config — this one SHOULD ride across.
    (root / ".claude" / "settings.local.json").write_text('{"local": true}\n')
    return root


@pytest.mark.parametrize("template", TEMPLATES)
def test_tracked_file_keeps_the_worktrees_own_version(
    template: str,
    repo_root: Path,
    origin: Path,
    stub_bin: Path,
    tmp_path: Path,
) -> None:
    worktree = _add_worktree(origin=origin, path=tmp_path / "wt")

    _run_hook(
        template=template,
        repo_root=repo_root,
        origin=origin,
        worktree=worktree,
        stub_bin=stub_bin,
    )

    assert (worktree / ".claude" / "rules" / "keep.md").read_text() == CURRENT_RULE


@pytest.mark.parametrize("template", TEMPLATES)
def test_fresh_worktree_has_no_uncommitted_changes(
    template: str,
    repo_root: Path,
    origin: Path,
    stub_bin: Path,
    tmp_path: Path,
) -> None:
    worktree = _add_worktree(origin=origin, path=tmp_path / "wt")

    _run_hook(
        template=template,
        repo_root=repo_root,
        origin=origin,
        worktree=worktree,
        stub_bin=stub_bin,
    )

    assert _git(worktree, "status", "--porcelain").stdout == ""


@pytest.mark.parametrize("template", TEMPLATES)
def test_gitignored_local_config_still_rides_across(
    template: str,
    repo_root: Path,
    origin: Path,
    stub_bin: Path,
    tmp_path: Path,
) -> None:
    """The fix must not throw out what the hook exists to carry."""
    worktree = _add_worktree(origin=origin, path=tmp_path / "wt")

    _run_hook(
        template=template,
        repo_root=repo_root,
        origin=origin,
        worktree=worktree,
        stub_bin=stub_bin,
    )

    assert (worktree / ".claude" / "settings.local.json").exists()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _add_worktree(*, origin: Path, path: Path) -> Path:
    _git(origin, "worktree", "add", str(path), "feature")
    return path


def _run_hook(
    *,
    template: str,
    repo_root: Path,
    origin: Path,
    worktree: Path,
    stub_bin: Path,
) -> None:
    source = repo_root / "skills" / "git-worktree" / "templates" / template
    patched = worktree.parent / f"hook-{template}"
    patched.write_text(
        source.read_text().replace(
            'ORIGINAL_REPO="/work/<org>/<project-name>"',
            f'ORIGINAL_REPO="{origin}"',
        )
    )
    patched.chmod(0o755)

    subprocess.run(
        ["sh", str(patched), NEW_WORKTREE_SHA, NEW_WORKTREE_SHA, "1"],
        cwd=worktree,
        capture_output=True,
        text=True,
        env={"PATH": f"{stub_bin}:/usr/local/bin:/usr/bin:/bin", "HOME": str(origin.parent)},
        check=True,
    )
