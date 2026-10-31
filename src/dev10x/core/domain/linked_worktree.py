"""Find the main checkout a linked worktree belongs to, without git.

A linked worktree's ``.git`` is a file holding ``gitdir: <main>/.git/
worktrees/<name>``; the main checkout is two levels above that path.
Reading it costs one small file read and no subprocess, which is what a
PreToolUse validator on the per-Bash-call latency budget can afford
(GH-1493) — ``git rev-parse --git-common-dir`` cannot be.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_GITDIR_PREFIX = "gitdir:"


def main_checkout(worktree_dir: Path) -> Path | None:
    """The main checkout for ``worktree_dir``, or ``None`` if it is not linked.

    Layout-free (GH-1666): the worktree can live anywhere. ``None`` covers
    a main checkout (``.git`` is a directory), a missing or unreadable
    ``.git``, and a ``gitdir:`` that is not a worktree pointer (e.g. a
    submodule's ``.git/modules/<name>``).
    """
    git_file = worktree_dir / ".git"
    if not git_file.is_file():
        return None
    try:
        content = git_file.read_text().strip()
    except (OSError, UnicodeDecodeError) as error:
        log.warning("cannot read %s, treated as not a linked worktree: %s", git_file, error)
        return None
    if not content.startswith(_GITDIR_PREFIX):
        return None
    gitdir = Path(content.removeprefix(_GITDIR_PREFIX).strip())
    if not gitdir.is_absolute():
        # worktree.useRelativePaths (git 2.48+) writes the gitdir relative
        # to the worktree, not to the process CWD.
        gitdir = (worktree_dir / gitdir).resolve()
    if "/worktrees/" not in str(gitdir):
        return None
    return gitdir.parent.parent.parent
