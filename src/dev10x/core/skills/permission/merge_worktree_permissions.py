"""Merge permissions from worktree settings back into the main project.

Worktrees accumulate session-specific allow rules that the main project
never sees. This module collects stable, reusable permissions from all
worktrees of a project and merges them into the main project's
settings.local.json.

Session-specific entries (temp file hashes, specific ticket numbers,
one-off inline commands) are filtered out automatically.

CLI entry point: ``dev10x permission merge-worktree``.
"""

import json
import logging
import re
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.mktmp_path import MKTMP_GENERALIZE_PATTERN, MKTMP_PATH_PATTERN
from dev10x.domain.common.policy import Policy, PolicySource
from dev10x.domain.common.result import Result
from dev10x.domain.common.ticket_id import TICKET_ID_PATTERN
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.permission.backup import backed_up_write
from dev10x.skills.permission.catalog_paths import shipped_projects_catalog
from dev10x.skills.permission.catalog_write import partition_writable
from dev10x.skills.permission.config import parse_config, resolve_config
from dev10x.skills.permission.policy_authoring import policy_from_accepted_prompt
from dev10x.skills.permission.settings_discovery import (
    VENDORED_DIRS,
    git_registered_worktrees,
    resolve_main_project,
    walk_repos,
)

MEMORY_CONFIG = Dev10xConfigDir.projects_yaml()
USERSPACE_CONFIG = Dev10xConfigDir.upgrade_cleanup_projects_yaml()
PLUGIN_CONFIG = shipped_projects_catalog()

log = logging.getLogger(__name__)

NOISE_PATTERNS = [
    re.compile(r"\.[A-Za-z0-9]{8,}\.(txt|md|json)"),
    re.compile(MKTMP_PATH_PATTERN),
    re.compile(r"GROOM_SEQ_FILE="),
    re.compile(rf'"{TICKET_ID_PATTERN}"'),
    re.compile(r"detect-tracker\.sh\s+\S"),
    re.compile(r"gh-issue-get\.sh\s+\d"),
    re.compile(r"gh-pr-detect\.sh\s+\d"),
    re.compile(r"generate-commit-list\.sh\s+\d"),
    re.compile(r"generate-commit-list\.sh\s+PLACEHOLDER"),
    re.compile(r"extract-session\.sh\s+"),
    re.compile(r"\.local/.*\.py\s+/tmp/"),
    re.compile(r"\s+2>&1"),
    re.compile(r'\.sh\)"?\s*$'),
    re.compile(r"git-push-safe\.sh\s+-u\s+origin\s+\S+/"),
    # Source-line references (e.g. features/foo.feature:60, bar.py:42)
    re.compile(r"\.(?:feature|py|js|ts|tsx|sh|md):\d+"),
]

# Bash-inner noise patterns (moved off the raw string, GH-841): each used to
# be anchored on the literal ``Bash(`` prefix; now matched against
# ``AllowRule.parse(entry).inner`` so the Bash-wrapper handling lives in one
# place. Anchored with ``^`` since the ``Bash(`` prefix guaranteed the match
# started at the beginning of the parenthesized body.
BASH_INNER_NOISE_PATTERNS = [
    re.compile(r"^if \["),
    re.compile(r"^then "),
    re.compile(r"^else "),
    re.compile(r"^fi\b"),
    re.compile(r"^bash -[nc] "),
    re.compile(r"^bash -c '"),
    re.compile(r"^find "),
]

GENERALIZE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(detect-tracker\.sh)\s+[^:)]+"), r"\1"),
    (re.compile(r"(gh-issue-get\.sh)\s+[^:)]+"), r"\1"),
    (re.compile(r"(gh-pr-detect\.sh)\s+[^:)]+"), r"\1"),
    (re.compile(r"(generate-commit-list\.sh)\s+[^:)]+"), r"\1"),
    (re.compile(r"(extract-session\.sh)\s+[^:)]+"), r"\1"),
    (re.compile(MKTMP_GENERALIZE_PATTERN), r"\1**"),
    (re.compile(r"(\.[A-Za-z0-9]{8,})\.(txt|md|json)"), r"**"),
    (re.compile(r"(git reset --hard) origin/\S+"), r"\1"),
    (re.compile(r"(git reset --soft) [A-Fa-f0-9]{6,}"), r"\1"),
    # Re-anchor worktree-absolute project paths to the project root so a
    # script approved inside a worktree (e.g. ``/work/dx/.worktrees/wt/bin/
    # release.sh``) syncs to the main project (``/work/dx/bin/release.sh``)
    # instead of being dropped as stale. Default anchor is project-root
    # absolute (GH-594, D12). Residual noise (temp hashes, source-line refs)
    # is still caught by NOISE_PATTERNS after re-anchoring.
    (re.compile(r"/\.worktrees/[^/]+/"), "/"),
]


def generalize_permission(entry: str) -> str:
    for pattern, replacement in GENERALIZE_PATTERNS:
        entry = pattern.sub(replacement, entry)
    return entry


def _herdr_sibling_pattern(*, main_project: Path) -> re.Pattern[str]:
    """Any herdr worktree of this repo, live or retired, in ``~`` or absolute form."""
    repo = re.escape(main_project.name)
    return re.compile(rf"(?:~|/[^\s()'\"]*?)/\.herdr/worktrees/{repo}/[^/\s()'\"]+/")


def reanchor_worktree_paths(
    entry: str,
    *,
    main_project: Path,
    worktree_roots: list[Path],
) -> str:
    """Point a rule pinned inside a worktree at the same path in the main checkout.

    The ``/.worktrees/<name>/`` regex in :data:`GENERALIZE_PATTERNS` only
    knows one layout (GH-1666). Herdr puts worktrees at
    ``<herdr-root>/worktrees/<repo>/<name>``, so their rules synced to the
    main checkout still named a worktree path — dead everywhere else, and
    dead in the worktree too once it was retired. Every root git has
    registered for the project is rewritten, in absolute and ``~`` form,
    longest first so ``wt-10/`` is never consumed as ``wt-1/``; a herdr
    path naming this repo is rewritten even when its worktree is gone.
    """
    main = f"{main_project}/"
    home = f"{Path.home()}/"
    for root in sorted({str(root) for root in worktree_roots}, key=len, reverse=True):
        entry = entry.replace(f"{root}/", main)
        if root.startswith(home):
            entry = entry.replace(f"~/{root[len(home) :]}/", main)
    return _herdr_sibling_pattern(main_project=main_project).sub(main, entry)


def find_config() -> Result[Path]:
    candidates = [MEMORY_CONFIG, USERSPACE_CONFIG]
    if PLUGIN_CONFIG is not None:
        candidates.append(PLUGIN_CONFIG)
    return resolve_config(candidates=candidates)


def load_config(config_path: Path) -> dict:
    return parse_config(config_path)


def is_noise(entry: str) -> bool:
    if any(p.search(entry) for p in NOISE_PATTERNS):
        return True
    parsed = AllowRule.parse(entry)
    return parsed.tool == "Bash" and any(p.search(parsed.inner) for p in BASH_INNER_NOISE_PATTERNS)


def sync_candidates_as_policies(*, entries: list[str]) -> list[Policy]:
    """Wrap stable worktree rules as candidate Policies (PAP-4, GH-801).

    The worktree→main sync is an accepted-prompt persistence flow: each
    stable entry becomes a ``project-local`` candidate Policy so the
    merge carries provenance instead of bare strings. Noise entries are
    dropped here, operating on the policy set rather than the raw list.
    """
    candidates = [
        policy_from_accepted_prompt(
            rule=entry,
            source=PolicySource.PROJECT_LOCAL,
            rationale="worktree sync (GH-603)",
        )
        for entry in entries
    ]
    return [policy for policy in candidates if not is_noise(policy.signature)]


def find_worktree_groups(roots: list[str]) -> dict[Path, list[Path]]:
    """Group each root's worktrees under their main project.

    Discovery unions two sources (GH-813 Finding 2): the conventional
    ``<root>/.worktrees/*`` glob (back-compat) and every worktree git has
    registered for the root via ``git worktree list`` (captures worktrees
    living anywhere). The main worktree is filtered out by
    ``resolve_main_project`` (its ``.git`` is a directory, not a linked
    ``gitdir:`` file), and only worktrees carrying a
    ``.claude/settings.local.json`` are grouped.
    """
    groups: dict[Path, list[Path]] = {}
    for root in roots:
        root_path = Path(root).expanduser()
        # Preserve insertion order while de-duplicating across the two
        # discovery sources (a worktree under .worktrees/ is also
        # git-registered).
        candidates: dict[Path, None] = {}
        worktrees_dir = root_path / ".worktrees"
        if worktrees_dir.is_dir():
            for wt_dir in sorted(worktrees_dir.iterdir()):
                if wt_dir.is_dir():
                    candidates[wt_dir] = None
        for wt_dir in git_registered_worktrees(root_path):
            candidates[wt_dir] = None
        for wt_dir in sorted(candidates):
            settings = wt_dir / ".claude" / "settings.local.json"
            if not settings.exists():
                continue
            main_project = resolve_main_project(wt_dir)
            if main_project is None:
                continue
            if wt_dir not in groups.setdefault(main_project, []):
                groups[main_project].append(wt_dir)
    return groups


def load_permissions(settings_path: Path) -> dict:
    if not settings_path.exists():
        return {}
    with open(settings_path) as f:
        return json.load(f)


def extract_allow_set(data: dict) -> set[str]:
    return set(data.get("permissions", {}).get("allow", []))


def merge_permissions(
    *,
    main_project: Path,
    worktree_dirs: list[Path],
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    main_settings = main_project / ".claude" / "settings.local.json"
    main_data = load_permissions(main_settings)
    main_allow = extract_allow_set(main_data)

    worktree_roots = [*worktree_dirs, *git_registered_worktrees(main_project)]
    generalized: set[str] = set()
    source_map: dict[str, list[Path]] = {}
    for wt_dir in worktree_dirs:
        wt_settings = wt_dir / ".claude" / "settings.local.json"
        wt_data = load_permissions(wt_settings)
        wt_allow = extract_allow_set(wt_data)
        for entry in wt_allow - main_allow:
            anchored = reanchor_worktree_paths(
                entry,
                main_project=main_project,
                worktree_roots=worktree_roots,
            )
            stable = generalize_permission(anchored)
            generalized.add(stable)
            source_map.setdefault(stable, []).append(wt_settings)

    generalized -= main_allow
    candidates = sync_candidates_as_policies(entries=sorted(generalized))
    stable_entries = [policy.signature for policy in candidates]

    if not stable_entries:
        return 0, []

    messages = [
        f"  target: {main_settings}",
        f"  +{len(stable_entries)} permissions from {len(worktree_dirs)} worktrees",
    ]
    for entry in stable_entries:
        sources = source_map.get(entry, [])
        if sources:
            source_paths = ", ".join(str(s) for s in sources)
            messages.append(f"    + {entry}")
            messages.append(f"      from: {source_paths}")
        else:
            messages.append(f"    + {entry}")

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(main_settings)
        with locked_json_update(path=main_settings) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            if "allow" not in live_data["permissions"]:
                live_data["permissions"]["allow"] = []
            existing = set(live_data["permissions"]["allow"])
            live_data["permissions"]["allow"].extend(
                e for e in stable_entries if e not in existing
            )

    return len(stable_entries), messages


def find_repo_families(
    roots: list[str],
    *,
    excluded: frozenset[str] = VENDORED_DIRS,
) -> dict[Path, list[Path]]:
    """Map each main checkout under ``roots`` to its worktrees that carry settings.

    Unlike :func:`find_worktree_groups`, a root may be a container of many
    repos (``/work/tt``), and a worktree may live anywhere on disk:
    ``git worktree list`` names the main checkout first and every linked
    worktree after it (GH-1673).
    """
    families: dict[Path, list[Path]] = {}
    seen: set[Path] = set()
    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
        for repo in walk_repos(root_path, excluded=excluded):
            if repo.resolve() in seen:
                continue
            family = git_registered_worktrees(repo)
            seen.update(member.resolve() for member in family)
            if len(family) < 2:
                continue
            main, *linked = family
            worktrees = [wt for wt in linked if (wt / ".claude" / "settings.local.json").is_file()]
            if worktrees and (main / ".claude" / "settings.local.json").is_file():
                families[main] = worktrees
    return families


def _home_relative(path: Path) -> str | None:
    home = Path.home()
    return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else None


def pins_a_checkout(entry: str, *, checkouts: list[Path]) -> bool:
    """True when ``entry`` names a path inside one checkout of the family.

    Such a rule only makes sense where it was granted (GH-1673, GH-1666):
    copying ``Bash(/work/proj/bin/x.sh:*)`` into a sibling worktree grants
    a script in the main checkout from inside the worktree, which is the
    cross-checkout pinning the doctor's invariants already reject.
    """
    for checkout in checkouts:
        spellings = [str(checkout), _home_relative(checkout)]
        if any(spelling and f"{spelling}/" in entry for spelling in spellings):
            return True
    return False


def _read_allow(settings: Path) -> set[str] | None:
    """The file's allow rules, or ``None`` when it cannot be read or parsed."""
    try:
        return extract_allow_set(load_permissions(settings))
    except (OSError, ValueError, AttributeError) as error:
        log.warning("cannot read %s: %s", settings, error)
        return None


def sync_main_to_worktrees(
    *,
    main_project: Path,
    worktree_dirs: list[Path],
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Copy rules granted in the main checkout into its existing worktrees.

    Propagation used to be one-shot (GH-1673): a worktree got a snapshot
    at creation, and ``merge-worktree`` only flows worktree → main. A
    "don't ask again" answered in the main checkout after the worktrees
    existed never reached them, so each kept prompting for a tool the
    repo had already approved. Rules pinned to a checkout path and
    session noise stay where they are.
    """
    main_settings = main_project / ".claude" / "settings.local.json"
    main_allow = _read_allow(main_settings)
    if main_allow is None:
        return 0, [f"  SKIP (unreadable settings): {main_settings}"]
    family = [main_project, *worktree_dirs]
    portable = sorted(
        entry
        for entry in main_allow
        if not pins_a_checkout(entry, checkouts=family) and not is_noise(entry)
    )
    targets = [wt / ".claude" / "settings.local.json" for wt in worktree_dirs]
    writable, messages = partition_writable(targets)

    total = 0
    for settings in writable:
        present = _read_allow(settings)
        if present is None:
            messages.append(f"  SKIP (unreadable settings): {settings}")
            continue
        missing = [entry for entry in portable if entry not in present]
        if not missing:
            continue
        total += len(missing)
        messages.append(f"  target: {settings}")
        messages.extend(f"    + {entry}" for entry in missing)
        if dry_run:
            continue
        with backed_up_write(path=settings) as live_data:
            allow = live_data.setdefault("permissions", {}).setdefault("allow", [])
            allow.extend(entry for entry in missing if entry not in allow)
    return total, messages


def _restore(*, config_path: Path) -> int:
    from dev10x.skills.permission.backup import restore_report

    config = load_config(config_path)
    roots = config.get("roots", [])
    groups = find_worktree_groups(roots)
    main_settings = [main_project / ".claude" / "settings.local.json" for main_project in groups]
    code, report = restore_report(paths=main_settings)
    print(report)
    return code
