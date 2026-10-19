"""Find every settings file a permission sweep governs (GH-1626).

``ensure-base``, ``catalog-gap`` and ``clean`` used to rglob
``.claude/settings.local.json`` under the configured roots. That missed
every worktree living outside the roots (``~/.herdr/worktrees/...``) and
walked into ``node_modules``, seeding rules into vendored packages.

Discovery now walks each root with vendored directories pruned, then
asks git for the worktrees of every repo it met, wherever they live on
disk. GH-813 already did the git half for ``merge-worktree``;
``git_registered_worktrees`` moved here so both paths share it.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.claude_paths import ClaudeDir

VENDORED_DIRS = frozenset(
    {"node_modules", ".venv", "venv", ".tox", ".git", "dist", "build", "site-packages"}
)
GIT_WORKTREE_TIMEOUT_SECONDS = 10
SETTINGS_DIR = ".claude"
SETTINGS_NAME = "settings.local.json"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SettingsDiscovery:
    files: list[Path]
    out_of_roots: list[Path]


def git_registered_worktrees(root_path: Path) -> list[Path]:
    """Worktree paths git has registered for the repo at ``root_path``.

    Uses ``git worktree list --porcelain`` so worktrees registered *outside*
    the conventional ``<root>/.worktrees/`` layout are discovered too
    (GH-813 Finding 2). A non-repo, a missing git, or a hung git all
    degrade to ``[]`` so one bad repo never aborts the sweep.
    """
    try:
        result = subprocess_utils.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(root_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_WORKTREE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        log.warning(
            "git worktree list timed out after %ss in %s; its worktrees are skipped",
            GIT_WORKTREE_TIMEOUT_SECONDS,
            root_path,
        )
        return []
    except OSError as exc:
        log.warning("git worktree list could not run in %s: %s", root_path, exc)
        return []
    if result.returncode != 0:
        log.warning(
            "git worktree list exited %s in %s; its worktrees are skipped",
            result.returncode,
            root_path,
        )
        return []
    return [
        Path(line[len("worktree ") :].strip())
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def outside_roots(*, files: list[Path], roots: list[str]) -> list[Path]:
    """Settings files that sit under no configured root and outside ``~/.claude``.

    Discovery only reaches such a file through ``git worktree list``, so
    this is exactly the set of worktrees the configured roots do not cover.
    """
    anchors = [Path(root).expanduser().resolve() for root in roots]
    anchors.append(ClaudeDir.home().resolve())
    return [
        path
        for path in files
        if not any(Path(path).resolve().is_relative_to(anchor) for anchor in anchors)
    ]


def _walk_root(root_path: Path) -> tuple[list[Path], list[Path]]:
    settings: list[Path] = []
    repos: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        current = Path(dirpath)
        if ".git" in dirnames or ".git" in filenames:
            repos.append(current)
        if current.name == SETTINGS_DIR and SETTINGS_NAME in filenames:
            settings.append(current / SETTINGS_NAME)
        dirnames[:] = sorted(name for name in dirnames if name not in VENDORED_DIRS)
    return settings, repos


def _worktree_settings(repos: list[Path]) -> list[Path]:
    known_worktrees: set[Path] = set()
    found: list[Path] = []
    for repo in repos:
        if repo.resolve() in known_worktrees:
            continue
        for worktree in git_registered_worktrees(repo):
            known_worktrees.add(worktree.resolve())
            candidate = worktree / SETTINGS_DIR / SETTINGS_NAME
            if candidate.is_file():
                found.append(candidate)
    return found


def _dedupe(paths: list[Path]) -> list[Path]:
    unique: dict[Path, None] = {}
    for path in paths:
        unique.setdefault(path.resolve(), None)
    return list(unique)


def discover_settings(*, roots: list[str], include_user: bool) -> SettingsDiscovery:
    files: list[Path] = []
    if include_user:
        user_dir = ClaudeDir.home()
        for name in ("settings.json", SETTINGS_NAME):
            candidate = user_dir / name
            if candidate.exists():
                files.append(candidate)

    project_settings_dir = ClaudeDir.projects_dir()
    if project_settings_dir.is_dir():
        files.extend(project_settings_dir.rglob(SETTINGS_NAME))

    repos: list[Path] = []
    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
        root_settings, root_repos = _walk_root(root_path)
        files.extend(root_settings)
        repos.extend(root_repos)

    worktree_files = _dedupe(_worktree_settings(repos))
    files.extend(worktree_files)
    return SettingsDiscovery(
        files=_dedupe(files),
        out_of_roots=outside_roots(files=worktree_files, roots=roots),
    )
