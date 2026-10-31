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
from dataclasses import dataclass, field
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.linked_worktree import main_checkout

VENDORED_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "vendor",
        ".tox",
        ".git",
        "dist",
        "build",
        "site-packages",
    }
)
EXCLUDE_DIRS_KEY = "exclude_dirs"
GIT_WORKTREE_TIMEOUT_SECONDS = 10
SETTINGS_DIR = ".claude"
SETTINGS_NAME = "settings.local.json"

log = logging.getLogger(__name__)


def vendored_dirs(config: dict) -> frozenset[str]:
    """The directory names every walk prunes: the built-in set plus the user's.

    ``exclude_dirs`` in the userspace catalog names extra directories a
    machine needs skipped (GH-1600). A non-list value or a non-string
    entry is ignored, matching the defensive parsing of other catalog keys.
    """
    extra = config.get(EXCLUDE_DIRS_KEY)
    if not isinstance(extra, list):
        return VENDORED_DIRS
    return VENDORED_DIRS | {name for name in extra if isinstance(name, str) and name}


@dataclass(frozen=True)
class SettingsDiscovery:
    files: list[Path]
    out_of_roots: list[Path]
    missing: list[Path] = field(default_factory=list)


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


def resolve_main_project(worktree_dir: Path) -> Path | None:
    """The main checkout a linked worktree belongs to (GH-1666).

    Delegates to the subprocess-free domain parser DX017 shares (GH-1493).
    """
    return main_checkout(worktree_dir)


def linked_worktree_roots(checkouts: list[Path]) -> list[str]:
    """Parent dirs of the linked worktrees that live outside their main checkout.

    These are the roots a user would otherwise register by hand under
    ``additionalDirectories`` (GH-1666): ``/work/.herdr/worktrees/<repo>``
    for a herdr worktree, ``<repo>/.worktrees`` needing nothing since it
    sits inside the main checkout already.
    """
    roots: dict[str, None] = {}
    for checkout in checkouts:
        main = resolve_main_project(checkout)
        if main is None or checkout.resolve().is_relative_to(main.resolve()):
            continue
        roots.setdefault(str(checkout.parent), None)
    return sorted(roots)


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


def _walk_root(
    root_path: Path,
    *,
    excluded: frozenset[str] = VENDORED_DIRS,
) -> tuple[list[Path], list[Path]]:
    settings: list[Path] = []
    repos: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        current = Path(dirpath)
        if ".git" in dirnames or ".git" in filenames:
            repos.append(current)
        if current.name == SETTINGS_DIR and SETTINGS_NAME in filenames:
            settings.append(current / SETTINGS_NAME)
        dirnames[:] = sorted(name for name in dirnames if name not in excluded)
    return settings, repos


def walk_repos(
    root_path: Path,
    *,
    excluded: frozenset[str] = VENDORED_DIRS,
) -> list[Path]:
    """Every directory under ``root_path`` holding a ``.git`` entry, vendored dirs pruned."""
    _settings, repos = _walk_root(root_path, excluded=excluded)
    return repos


def _worktree_settings(repos: list[Path]) -> tuple[list[Path], list[Path]]:
    """Settings files of every git-registered worktree, and the ones missing.

    A worktree's file counts as *missing* only when a sibling checkout of
    the same repo has one (GH-1664): the user opted that repo in, and a
    worktree created outside ``dev10x:git-worktree`` — a herdr worktree,
    a raw ``git worktree add`` — otherwise reads only the global files.
    A repo with no settings file anywhere is left alone.
    """
    known_worktrees: set[Path] = set()
    found: list[Path] = []
    missing: list[Path] = []
    for repo in repos:
        if repo.resolve() in known_worktrees:
            continue
        family = git_registered_worktrees(repo)
        candidates = [worktree / SETTINGS_DIR / SETTINGS_NAME for worktree in family]
        known_worktrees.update(worktree.resolve() for worktree in family)
        present = [candidate for candidate in candidates if candidate.is_file()]
        found.extend(present)
        if present:
            # `git worktree list` names the main checkout first; only the
            # linked worktrees after it are created on the user's behalf.
            missing.extend(
                candidate
                for candidate in candidates[1:]
                if not candidate.is_file() and candidate.parent.parent.is_dir()
            )
    return found, missing


def _dedupe(paths: list[Path]) -> list[Path]:
    unique: dict[Path, None] = {}
    for path in paths:
        unique.setdefault(path.resolve(), None)
    return list(unique)


def discover_settings(
    *,
    roots: list[str],
    include_user: bool,
    excluded: frozenset[str] = VENDORED_DIRS,
) -> SettingsDiscovery:
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
        root_settings, root_repos = _walk_root(root_path, excluded=excluded)
        files.extend(root_settings)
        repos.extend(root_repos)

    found, missing = _worktree_settings(repos)
    worktree_files = _dedupe(found)
    files.extend(worktree_files)
    return SettingsDiscovery(
        files=_dedupe(files),
        out_of_roots=outside_roots(files=worktree_files, roots=roots),
        missing=_dedupe(missing),
    )
