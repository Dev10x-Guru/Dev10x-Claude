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
import re
from pathlib import Path

from dev10x.domain.common.mktmp_path import MKTMP_GENERALIZE_PATTERN, MKTMP_PATH_PATTERN
from dev10x.domain.common.policy import Policy, PolicySource
from dev10x.domain.common.result import Result
from dev10x.domain.common.ticket_id import TICKET_ID_PATTERN
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.permission.config import parse_config, resolve_config
from dev10x.skills.permission.policy_authoring import policy_from_accepted_prompt

MEMORY_CONFIG = Dev10xConfigDir.projects_yaml()
USERSPACE_CONFIG = Dev10xConfigDir.upgrade_cleanup_projects_yaml()
PLUGIN_CONFIG = (
    Path(__file__).resolve().parents[4] / "skills" / "upgrade-cleanup" / "projects.yaml"
)

NOISE_PATTERNS = [
    re.compile(r"\.[A-Za-z0-9]{8,}\.(txt|md|json)"),
    re.compile(MKTMP_PATH_PATTERN),
    re.compile(r"Bash\(if \["),
    re.compile(r"Bash\(then "),
    re.compile(r"Bash\(else "),
    re.compile(r"Bash\(fi\b"),
    re.compile(r"GROOM_SEQ_FILE="),
    re.compile(rf'"{TICKET_ID_PATTERN}"'),
    re.compile(r"detect-tracker\.sh\s+\S"),
    re.compile(r"gh-issue-get\.sh\s+\d"),
    re.compile(r"gh-pr-detect\.sh\s+\d"),
    re.compile(r"generate-commit-list\.sh\s+\d"),
    re.compile(r"generate-commit-list\.sh\s+PLACEHOLDER"),
    re.compile(r"extract-session\.sh\s+"),
    re.compile(r"Bash\(bash -[nc] "),
    re.compile(r"Bash\(bash -c '"),
    re.compile(r"\.local/.*\.py\s+/tmp/"),
    re.compile(r"\s+2>&1"),
    re.compile(r'\.sh\)"?\s*$'),
    re.compile(r"git-push-safe\.sh\s+-u\s+origin\s+\S+/"),
    re.compile(r"Bash\(find "),
    # Source-line references (e.g. features/foo.feature:60, bar.py:42)
    re.compile(r"\.(?:feature|py|js|ts|tsx|sh|md):\d+"),
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


def find_config() -> Result[Path]:
    return resolve_config(candidates=[MEMORY_CONFIG, USERSPACE_CONFIG, PLUGIN_CONFIG])


def load_config(config_path: Path) -> dict:
    return parse_config(config_path)


def is_noise(entry: str) -> bool:
    return any(p.search(entry) for p in NOISE_PATTERNS)


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


def resolve_main_project(worktree_dir: Path) -> Path | None:
    git_file = worktree_dir / ".git"
    if not git_file.is_file():
        return None
    content = git_file.read_text().strip()
    if not content.startswith("gitdir:"):
        return None
    gitdir = content.split(":", 1)[1].strip()
    gitdir_path = Path(gitdir)
    if "/worktrees/" not in str(gitdir_path):
        return None
    main_git_dir = gitdir_path.parent.parent
    return main_git_dir.parent


def find_worktree_groups(roots: list[str]) -> dict[Path, list[Path]]:
    groups: dict[Path, list[Path]] = {}
    for root in roots:
        root_path = Path(root).expanduser()
        worktrees_dir = root_path / ".worktrees"
        if not worktrees_dir.is_dir():
            continue
        for wt_dir in sorted(worktrees_dir.iterdir()):
            if not wt_dir.is_dir():
                continue
            settings = wt_dir / ".claude" / "settings.local.json"
            if not settings.exists():
                continue
            main_project = resolve_main_project(wt_dir)
            if main_project is None:
                continue
            groups.setdefault(main_project, []).append(wt_dir)
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

    new_entries: set[str] = set()
    source_map: dict[str, list[Path]] = {}
    for wt_dir in worktree_dirs:
        wt_settings = wt_dir / ".claude" / "settings.local.json"
        wt_data = load_permissions(wt_settings)
        wt_allow = extract_allow_set(wt_data)
        for entry in wt_allow - main_allow:
            new_entries.add(entry)
            source_map.setdefault(entry, []).append(wt_settings)

    generalized = {generalize_permission(e) for e in new_entries}
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


def _restore(*, config_path: Path) -> int:
    from dev10x.skills.permission.backup import restore_report

    config = load_config(config_path)
    roots = config.get("roots", [])
    groups = find_worktree_groups(roots)
    main_settings = [main_project / ".claude" / "settings.local.json" for main_project in groups]
    code, report = restore_report(paths=main_settings)
    print(report)
    return code
