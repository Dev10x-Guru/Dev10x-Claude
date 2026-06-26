"""Session Place provisioning — temp directories and git alias inventory.

Place archetype: side effects that prepare the workspace for a session
(creating ``/tmp/Dev10x/<session_id>``) and surface infrastructure
state to the user (which git alias shortcuts are wired up). Split out
of ``hooks/session.py`` so the dispatcher stays at event-routing scope.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from dev10x.domain.git_context import GitContext

BASE_BRANCH_ALIASES: tuple[str, ...] = (
    "nopager",
    "nocolor",
    "develop-log",
    "develop-diff",
    "develop-rebase",
    "autosquash-develop",
    "development-log",
    "development-diff",
    "development-rebase",
    "autosquash-development",
    "trunk-log",
    "trunk-diff",
    "trunk-rebase",
    "autosquash-trunk",
    "main-log",
    "main-diff",
    "main-rebase",
    "autosquash-main",
    "master-log",
    "master-diff",
    "master-rebase",
    "autosquash-master",
)


def _run_git(*args: str) -> str:
    try:
        return GitContext().run(*args)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def session_tmpdir(data: dict | None = None) -> None:
    """Create session scratch directory and install mktmp.sh (SessionStart hook)."""
    if data is None:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            sys.exit(0)

    session_id = data.get("session_id") or ""
    if not session_id:
        return

    Path(f"/tmp/Dev10x/{session_id}").mkdir(parents=True, exist_ok=True)

    plugin_root = Path(__file__).parents[3]
    mktmp_src = plugin_root / "bin" / "mktmp.sh"
    dest_bin = Path("/tmp/Dev10x/bin")
    dest_bin.mkdir(parents=True, exist_ok=True)

    if mktmp_src.exists():
        dest = dest_bin / "mktmp.sh"
        shutil.copy2(src=mktmp_src, dst=dest)
        dest.chmod(0o755)


def session_git_aliases() -> None:
    """Check git branch-comparison aliases and report status (SessionStart hook)."""
    missing: list[str] = []
    present: list[str] = []
    for alias in BASE_BRANCH_ALIASES:
        if _run_git("config", "--get", f"alias.{alias}"):
            present.append(alias)
        else:
            missing.append(alias)

    if not missing:
        print(f"Git aliases available: {' '.join(present)}")
        print("Use `git {base}-log`, `git {base}-diff`, `git {base}-rebase`")
        print("instead of $(git merge-base ...) to avoid permission prompts.")
        return

    print(f"Git aliases missing: {' '.join(missing)}")
    if present:
        print(f"Git aliases available: {' '.join(present)}")
    print("Run the git-alias-setup skill (/Dev10x:git-alias-setup) to configure them.")


__all__ = ["session_tmpdir", "session_git_aliases", "BASE_BRANCH_ALIASES"]
