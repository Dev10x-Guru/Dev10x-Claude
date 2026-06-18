"""Maintain Dev10x plugin permission settings across all projects.

Modes:
  - (default) Update versioned plugin cache paths to the latest version
  - ensure-base: Add missing base permissions from projects.yaml
  - generalize: Replace session-specific args with wildcard patterns

Config lookup order (post-GH-215):
  1. ~/.config/Dev10x/projects.yaml (XDG; legacy ~/.claude/memory/Dev10x/)
  2. ~/.config/Dev10x/upgrade-cleanup-projects.yaml (XDG; legacy
     ~/.claude/skills/Dev10x:upgrade-cleanup/projects.yaml)
  3. ${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/projects.yaml (plugin default)

CLI entry point: ``dev10x permission update-paths`` (and siblings).

GH-315 Bug C (resolved, GH-577): ``merge-worktree`` and ``clean`` now
read ``~/.config/Dev10x/projects.yaml`` (MEMORY_CONFIG) like every
other subcommand, falling back to the legacy
``~/.config/Dev10x/upgrade-cleanup-projects.yaml`` (USERSPACE_CONFIG)
only when ``projects.yaml`` is absent. ``init-userspace-config``
migrates the legacy file into ``projects.yaml`` on first use, so the
two no longer drift.
"""

import json
import re
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.mktmp_path import MKTMP_GENERALIZE_PATTERN
from dev10x.domain.common.plugin_version import SEMVER_PATTERN, PluginVersion
from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.plugin_identity import PLUGIN_NAMES
from dev10x.skills.permission.config import parse_config, resolve_config

MEMORY_CONFIG = Dev10xConfigDir.projects_yaml()
USERSPACE_CONFIG = Dev10xConfigDir.upgrade_cleanup_projects_yaml()
PLUGIN_CONFIG = (
    Path(__file__).resolve().parents[4] / "skills" / "upgrade-cleanup" / "projects.yaml"
)
VERSION_PATTERN = re.compile(rf"(plugins/cache/)([^/]+)(/{PLUGIN_NAMES}/)({SEMVER_PATTERN})")


def extract_cache_publisher(plugin_cache: str) -> str | None:
    path = Path(plugin_cache).expanduser()
    parts = list(path.parts)
    for i, part in enumerate(parts):
        if part == "cache" and i >= 2 and parts[i - 1] == "plugins":
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


def find_config() -> Result[Path]:
    return resolve_config(
        candidates=[MEMORY_CONFIG, USERSPACE_CONFIG, PLUGIN_CONFIG],
        create_path=MEMORY_CONFIG,
    )


def load_config(config_path: Path) -> dict:
    return parse_config(config_path)


def detect_latest_version(cache_dir: Path) -> str | None:
    if not cache_dir.is_dir():
        return None
    versions = sorted(
        cache_dir.iterdir(),
        key=lambda p: PluginVersion.sort_key(p.name),
    )
    return versions[-1].name if versions else None


def find_settings_files(
    roots: list[str],
    *,
    include_user: bool,
) -> list[Path]:
    files: list[Path] = []
    if include_user:
        user_dir = ClaudeDir.home()
        for name in ("settings.json", "settings.local.json"):
            candidate = user_dir / name
            if candidate.exists():
                files.append(candidate)

    project_settings_dir = ClaudeDir.projects_dir()
    if project_settings_dir.is_dir():
        for settings_file in project_settings_dir.rglob("settings.local.json"):
            files.append(settings_file)

    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
        for settings_file in root_path.rglob(".claude/settings.local.json"):
            files.append(settings_file)

    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _rewrite_plugin_version_match(
    match: re.Match,
    *,
    target_publisher: str | None,
    target_version: str,
) -> str:
    """Return the version/publisher-rewritten text for a single match.

    Pure helper shared by the counting pass and the locked re-apply so
    both agree on the replacement without double-counting.
    """
    prefix = match.group(1)
    publisher = match.group(2)
    plugin_slug = match.group(3)
    old_ver = match.group(4)
    new_publisher = (
        target_publisher if target_publisher and publisher != target_publisher else publisher
    )
    new_ver = target_version if old_ver != target_version else old_ver
    if new_publisher == publisher and new_ver == old_ver:
        return match.group(0)
    return prefix + new_publisher + plugin_slug + new_ver


def update_file(
    path: Path,
    target_version: str,
    *,
    target_publisher: str | None = None,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    content = path.read_text()
    old_versions: set[str] = set()
    old_publishers: set[str] = set()
    count = 0

    def replacer(match: re.Match) -> str:
        nonlocal count
        prefix = match.group(1)
        publisher = match.group(2)
        plugin_slug = match.group(3)
        old_ver = match.group(4)

        new_publisher = publisher
        new_ver = old_ver
        changed = False

        if target_publisher and publisher != target_publisher:
            old_publishers.add(publisher)
            new_publisher = target_publisher
            changed = True

        if old_ver != target_version:
            old_versions.add(old_ver)
            new_ver = target_version
            changed = True

        if changed:
            count += 1
            return prefix + new_publisher + plugin_slug + new_ver
        return match.group(0)

    new_content = VERSION_PATTERN.sub(replacer, content)

    if count > 0 and not dry_run:
        try:
            json.loads(new_content)
        except json.JSONDecodeError as e:
            return 0, [f"  SKIP (invalid JSON after replacement): {e}"]

        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            live_text = json.dumps(live_data, indent=2) + "\n"
            rewritten = VERSION_PATTERN.sub(
                lambda m: _rewrite_plugin_version_match(
                    m,
                    target_publisher=target_publisher,
                    target_version=target_version,
                ),
                live_text,
            )
            live_data.clear()
            live_data.update(json.loads(rewritten))

    messages = []
    for old_pub in sorted(old_publishers):
        messages.append(f"  publisher: {old_pub} -> {target_publisher}")
    for old_ver in sorted(old_versions):
        messages.append(f"  {old_ver} -> {target_version} ({count} replacements)")
    return count, messages


def ensure_base_permissions(
    path: Path,
    base_permissions: list[str],
    *,
    dry_run: bool = False,
    expand_mcp: bool = True,
    mcp_catalog: dict[str, list[str]] | None = None,
) -> tuple[int, list[str]]:
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    existing = {r for r in allow_list if not _is_nonfunctional_mcp_wildcard(r)}
    stale_wildcards = [r for r in allow_list if _is_nonfunctional_mcp_wildcard(r)]
    expanded_tools = _expand_stale_wildcards(
        stale_wildcards=stale_wildcards,
        existing=existing,
        enabled=expand_mcp,
        catalog=mcp_catalog,
    )
    if expanded_tools:
        existing.update(expanded_tools)
    missing = [p for p in base_permissions if p not in existing]

    if not missing and not stale_wildcards:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            if "allow" not in live_data["permissions"]:
                live_data["permissions"]["allow"] = []
            if stale_wildcards:
                live_data["permissions"]["allow"] = [
                    r
                    for r in live_data["permissions"]["allow"]
                    if not _is_nonfunctional_mcp_wildcard(r)
                ]
            live_data["permissions"]["allow"].extend(expanded_tools)
            live_data["permissions"]["allow"].extend(missing)

    messages = [f"  - {wc}  (non-functional MCP wildcard removed)" for wc in stale_wildcards]
    messages.extend(f"  + {tool}  (expanded from MCP wildcard)" for tool in expanded_tools)
    messages.extend(f"  + {p}" for p in missing)
    return len(missing) + len(stale_wildcards) + len(expanded_tools), messages


def ensure_base_denies(
    path: Path,
    base_denies: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Add missing base deny rules to a settings file's `permissions.deny` list.

    Denies are stricter than allows — they must be enforced per project even
    when a global setting allows the same operation. The presence of a deny
    rule in global settings does NOT excuse adding it to project settings,
    so this helper skips the global-rules filter that `ensure_base_permissions`
    uses for allows.
    """
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    deny_list: list[str] = data.get("permissions", {}).get("deny", [])
    existing = set(deny_list)
    missing = [d for d in base_denies if d not in existing]
    if not missing:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            if "deny" not in live_data["permissions"]:
                live_data["permissions"]["deny"] = []
            live_data["permissions"]["deny"].extend(missing)

    messages = [f"  + {d}  (deny)" for d in missing]
    return len(missing), messages


def _expand_stale_wildcards(
    *,
    stale_wildcards: list[str],
    existing: set[str],
    enabled: bool,
    catalog: dict[str, list[str]] | None = None,
) -> list[str]:
    """Expand stale MCP wildcards into enumerated tool names.

    Avoids the round-trip where ensure-base strips wildcards
    and a follow-up enumerate-mcp call would have to re-add
    the same tools the wildcard was meant to cover.

    `catalog` may be passed in by the caller to avoid re-running
    AST discovery once per settings file.
    """
    if not enabled or not stale_wildcards:
        return []

    if catalog is None:
        from dev10x.skills.permission.enumerate_mcp import discover_mcp_tools

        catalog = discover_mcp_tools()
    if not catalog:
        return []

    from dev10x.skills.permission.enumerate_mcp import _matches_wildcard

    expanded: list[str] = []
    seen = set(existing)
    for wildcard in stale_wildcards:
        for tool in _matches_wildcard(wildcard, catalog) or []:
            if tool not in seen:
                expanded.append(tool)
                seen.add(tool)
    return expanded


SCRIPT_SCAN_GLOBS: list[str] = [
    "bin/*.sh",
    "hooks/scripts/*.py",
    "hooks/scripts/*.sh",
    "skills/*/scripts/*.py",
    "skills/*/scripts/*.sh",
]

READ_TOP_LEVEL_DIRS: tuple[str, ...] = (
    "agents",
    "commands",
    "references",
    "hooks",
    "hooks/scripts",
    "bin",
    "servers",
    "lib",
)


def scan_plugin_scripts(plugin_root: Path) -> list[Path]:
    scripts: list[Path] = []
    for glob_pattern in SCRIPT_SCAN_GLOBS:
        scripts.extend(plugin_root.glob(glob_pattern))
    return sorted(set(scripts))


def build_script_allow_rules(
    scripts: list[Path],
    *,
    plugin_root: Path,
) -> list[str]:
    rules: list[str] = []
    for script in scripts:
        relative = script.relative_to(plugin_root)
        rules.append(str(AllowRule.bash(f"{plugin_root}/{relative}:*")))
    return rules


# GH-606 AC2: user-skill scripts under ~/.claude/skills/<dir>/scripts/.
# Personal skills keep the colon in the directory name (``my:daily-yt``);
# plugin-installed skills strip it (``daily-yt``). The glob matches both
# because the colon is a literal path character.
USER_SKILL_SCRIPT_GLOBS: list[str] = [
    "*/scripts/*.sh",
    "*/scripts/*.py",
]

# A credentialed pass-through wrapper execs a privileged CLI with the
# caller's argv. With a ``:*`` allow rule that grants *every* verb —
# including ``delete``/``apply`` (GH-606 evidence #4). A wrapper that
# declares a verb allowlist (kubectl.sh, aws.sh) is verb-aware and safe.
_CREDENTIALED_EXEC_RE = re.compile(
    r"\b(?:aws-vault\s+exec|vault\s+(?:login|read)|gcloud\s+auth)\b"
)
_PASSTHROUGH_ARGV_RE = re.compile(r'"\$@"')
_VERB_ALLOWLIST_RE = re.compile(r"ALLOWED_VERBS|ALLOWED_PREFIXES|ALLOWED_OPERATIONS")


def scan_user_skill_scripts(skills_root: Path) -> list[Path]:
    """Return executable scripts under ``skills_root/<dir>/scripts/`` (GH-606).

    ``skills_root`` is ``~/.claude/skills`` in production. Returns a sorted,
    de-duplicated list. Handles colon-kept personal-skill directories
    (``my:daily-yt``) and prefix-stripped plugin-skill directories alike.
    """
    if not skills_root.is_dir():
        return []
    scripts: list[Path] = []
    for glob_pattern in USER_SKILL_SCRIPT_GLOBS:
        scripts.extend(skills_root.glob(glob_pattern))
    return sorted(set(scripts))


def is_verb_blind_credentialed_wrapper(script: Path) -> bool:
    """True when *script* pipes ``"$@"`` to a credentialed CLI with no verb gate.

    Such a wrapper must NOT receive a ``:*`` allow rule (GH-606 AC2): the
    rule would authorize every verb the privileged CLI exposes. A wrapper
    that declares an ``ALLOWED_VERBS`` / ``ALLOWED_PREFIXES`` /
    ``ALLOWED_OPERATIONS`` allowlist is verb-aware (kubectl.sh, aws.sh) and
    is therefore safe at ``:*``. Unreadable scripts default to *not*
    verb-blind so a transient read error never silently widens nor narrows
    coverage on its own — the caller still gates on the allowlist marker.
    """
    try:
        text = script.read_text()
    except OSError:
        return False
    if not _CREDENTIALED_EXEC_RE.search(text):
        return False
    if _VERB_ALLOWLIST_RE.search(text):
        return False
    return bool(_PASSTHROUGH_ARGV_RE.search(text))


def build_user_skill_script_rules(
    scripts: list[Path],
    *,
    skills_root: Path,
    user_home: Path,
) -> tuple[list[str], list[Path]]:
    """Build canonical ``~/`` + ``/home/<user>/`` Bash rules for user scripts.

    Returns ``(rules, skipped)`` where *skipped* lists verb-blind
    credentialed pass-through wrappers that were intentionally NOT granted
    a ``:*`` rule (GH-606 AC2) — surfaced so the caller can log the gap
    rather than silently dropping them. Each emitted script gets a ``~/``
    rule and its resolved ``/home/<user>/`` twin (GH-271 #192/#215).
    """
    home = user_home.expanduser().resolve()
    try:
        rel_root = skills_root.relative_to(home)
    except ValueError:
        return [], []
    rules: list[str] = []
    skipped: list[Path] = []
    for script in scripts:
        if is_verb_blind_credentialed_wrapper(script):
            skipped.append(script)
            continue
        rel = script.relative_to(skills_root)
        rules.append(str(AllowRule.bash(f"~/{rel_root}/{rel}:*")))
        rules.append(str(AllowRule.bash(f"{home}/{rel_root}/{rel}:*")))
    return rules, skipped


def is_dead_glob_script_rule(entry: str) -> bool:
    """True for a Bash plugin-cache rule that uses a ``**`` glob (GH-471).

    Claude Code's Bash permission matcher treats ``**`` literally — the
    literal characters never appear in a real command string — so these
    rules never match. ``update-paths`` cannot repair them either, since
    its version regex only rewrites rules containing a literal ``X.Y.Z``.
    They are dead weight and must be purged in favour of concrete
    version-pinned rules emitted by :func:`build_script_allow_rules`.

    Scoped to ``Bash(`` cache rules so unversioned ``Read(... /**)``
    marketplaces rules (which are functional) are never touched.
    """
    return entry.startswith("Bash(") and "plugins/cache/" in entry and "**" in entry


def purge_dead_glob_script_rules(
    path: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Remove dead ``**`` cache-glob Bash rules from a settings file.

    Returns ``(count_removed, messages)``. Idempotent — a file with no
    dead globs returns ``(0, [])``.
    """
    try:
        content = path.read_text()
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        return 0, [f"  SKIP (unreadable JSON): {exc}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    dead = [r for r in allow_list if is_dead_glob_script_rule(r)]
    if not dead:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            allow = live_data.get("permissions", {}).get("allow", [])
            live_data["permissions"]["allow"] = [
                r for r in allow if not is_dead_glob_script_rule(r)
            ]

    messages = [f"  - {r}  (dead ** cache glob removed)" for r in dead]
    return len(dead), messages


def verify_script_coverage(
    settings_path: Path,
    expected_rules: list[str],
) -> tuple[list[str], list[str]]:
    content = settings_path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return [], expected_rules

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])

    covered: list[str] = []
    missing: list[str] = []
    for rule in expected_rules:
        match = re.search(r"Bash\((.+?):\*\)", rule)
        if not match:
            missing.append(rule)
            continue
        script_name = Path(match.group(1)).name
        pattern = re.compile(rf"Bash\(.*/{re.escape(script_name)}:\*\)")
        # GH-471: a ** cache glob never matches in Claude Code's Bash
        # matcher and update-paths cannot re-version it (no literal X.Y.Z
        # segment), so it is NOT real coverage. Skip dead globs here so a
        # concrete version-pinned rule is emitted instead.
        if rule in allow_list or any(
            pattern.search(entry) for entry in allow_list if not is_dead_glob_script_rule(entry)
        ):
            covered.append(rule)
        else:
            missing.append(rule)
    return covered, missing


def scan_skill_directories(
    plugin_root: Path,
) -> list[str]:
    """Return the list of skill directory names under plugin_root/skills."""
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def scan_top_level_dirs(
    plugin_root: Path,
) -> list[str]:
    """Return top-level subpaths under plugin_root that exist and contain files."""
    present: list[str] = []
    for sub in READ_TOP_LEVEL_DIRS:
        target = plugin_root / sub
        if target.is_dir():
            present.append(sub)
    return present


def build_marketplaces_read_rules(
    *,
    plugin_cache: str,
    user_home: Path,
) -> list[str]:
    """Emit unversioned Read rules pointing at the marketplaces layout.

    The runtime reads plugin skills from
    ``~/.claude/plugins/marketplaces/<publisher>/skills/...`` (unversioned).
    Versioned cache paths emitted by :func:`build_read_allow_rules` go
    stale on every plugin upgrade (GH-254). Emit an unversioned rule
    covering every skill at once so the Read allow-rule survives plugin
    version bumps.

    Returns ``~/`` and ``/home/<user>/`` twins covering the whole
    marketplaces publisher tree.
    """
    publisher = extract_cache_publisher(plugin_cache)
    if not publisher:
        return []

    home = user_home.expanduser().resolve()
    rel = f".claude/plugins/marketplaces/{publisher}"
    return [
        str(AllowRule.read(f"~/{rel}/**")),
        str(AllowRule.read(f"{home}/{rel}/**")),
    ]


def build_read_allow_rules(
    *,
    plugin_root: Path,
    user_home: Path,
) -> list[str]:
    """Build per-skill and per-top-level Read rules with ~/ + /home/<user>/ twins.

    For each skill folder and recognized top-level dir under
    plugin_root, emit two Read rules — one anchored at ``~/`` and
    one anchored at ``/home/<user>/`` — so the permission engine
    matches whichever shape the prompt uses.

    Both variants share the version segment, so :func:`update_file`'s
    version regex updates them in lockstep when the plugin upgrades.
    """
    home = user_home.expanduser().resolve()
    try:
        relative = plugin_root.relative_to(home)
    except ValueError:
        return []

    base_rel = str(relative)
    relpaths: list[str] = [base_rel]
    for skill in scan_skill_directories(plugin_root):
        relpaths.append(f"{base_rel}/skills/{skill}")
    for top in scan_top_level_dirs(plugin_root):
        relpaths.append(f"{base_rel}/{top}")

    rules: list[str] = []
    for rel in relpaths:
        rules.append(str(AllowRule.read(f"~/{rel}/*")))
        rules.append(str(AllowRule.read(f"{home}/{rel}/*")))
    return rules


def verify_read_coverage(
    settings_path: Path,
    expected_rules: list[str],
) -> tuple[list[str], list[str]]:
    """Return (covered, missing) Read rules for the given settings file.

    Matching is exact — Claude Code's permission engine compares
    rule strings literally. Wildcard expansion is not attempted.
    """
    content = settings_path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return [], expected_rules

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    allow_set = set(allow_list)

    covered: list[str] = []
    missing: list[str] = []
    for rule in expected_rules:
        if rule in allow_set:
            covered.append(rule)
        else:
            missing.append(rule)
    return covered, missing


def ensure_read_rules(
    settings_path: Path,
    missing_rules: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Append missing Read rules to ``settings_path``.

    Idempotent — only appends rules not already present. Backed up
    via :mod:`dev10x.skills.permission.backup`.
    """
    if not missing_rules:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(settings_path)
        with locked_json_update(path=settings_path) as data:
            if "permissions" not in data:
                data["permissions"] = {}
            if "allow" not in data["permissions"]:
                data["permissions"]["allow"] = []
            existing = set(data["permissions"]["allow"])
            for rule in missing_rules:
                if rule not in existing:
                    data["permissions"]["allow"].append(rule)
                    existing.add(rule)

    messages = [f"  + {rule}" for rule in missing_rules]
    return len(missing_rules), messages


def ensure_script_rules(
    settings_path: Path,
    missing_rules: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    if not missing_rules:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(settings_path)
        with locked_json_update(path=settings_path) as data:
            if "permissions" not in data:
                data["permissions"] = {}
            if "allow" not in data["permissions"]:
                data["permissions"]["allow"] = []
            data["permissions"]["allow"].extend(missing_rules)

    messages = [f"  + {rule}" for rule in missing_rules]
    return len(missing_rules), messages


# GH-269: Legacy `${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/`
# allow-rules rot on every plugin upgrade because the cache path
# encodes the version. The four scripts were retired in favour of
# the version-stable `uvx dev10x permission <subcommand>` CLI.
# `permission update-paths` migrates any surviving legacy rules to
# the matching CLI form so the user's settings stop drifting.
_LEGACY_UPGRADE_CLEANUP_SCRIPTS: dict[str, str] = {
    "update-paths.py": "uvx dev10x permission update-paths",
    "merge-worktree-permissions.py": "uvx dev10x permission merge-worktree",
    "clean-project-files.py": "uvx dev10x permission clean",
    "enumerate-mcp.py": "uvx dev10x permission enumerate-mcp",
}

_LEGACY_UPGRADE_CLEANUP_RULE_PATTERN = re.compile(
    r"^Bash\("
    r"(?:[^)]*?/)?skills/upgrade-cleanup/scripts/"
    r"(?P<script>[A-Za-z0-9_.-]+\.py)"
    r"(?::\*|\s+[^)]*)?"
    r"\)$"
)


def collapse_legacy_upgrade_cleanup_rule(entry: str) -> str | None:
    """Collapse a legacy upgrade-cleanup cache-path rule to the uvx form.

    Returns the replacement rule when ``entry`` matches one of the four
    retired shim scripts (GH-269). Returns ``None`` for unrelated rules.

    The match is intentionally tolerant of every cache-path shape that
    has appeared in user settings: ``${CLAUDE_PLUGIN_ROOT}/...``,
    ``~/.claude/plugins/cache/<pub>/<plugin>/<ver>/...``, and the
    fully-expanded ``/home/<user>/.claude/plugins/cache/.../`` form.
    """

    match = _LEGACY_UPGRADE_CLEANUP_RULE_PATTERN.match(entry)
    if not match:
        return None
    script = match.group("script")
    target_cmd = _LEGACY_UPGRADE_CLEANUP_SCRIPTS.get(script)
    if target_cmd is None:
        return None
    return str(AllowRule.bash(f"{target_cmd}:*"))


def collapse_legacy_upgrade_cleanup_rules(
    path: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Rewrite legacy upgrade-cleanup script rules in a settings file."""

    try:
        content = path.read_text()
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        return 0, [f"  SKIP (unreadable JSON): {exc}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    if not allow_list:
        return 0, []

    seen: set[str] = set()
    new_allow: list[str] = []
    replacements: list[tuple[str, str]] = []
    for entry in allow_list:
        collapsed = collapse_legacy_upgrade_cleanup_rule(entry)
        if collapsed is None:
            if entry not in seen:
                new_allow.append(entry)
                seen.add(entry)
            continue
        replacements.append((entry, collapsed))
        if collapsed not in seen:
            new_allow.append(collapsed)
            seen.add(collapsed)

    if not replacements:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            live_data["permissions"]["allow"] = new_allow

    messages = [f"  {old} → {new}" for old, new in replacements]
    return len(replacements), messages


GENERALIZE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(detect-tracker\.sh)\s+[^)]+"), r"\1:*"),
    (re.compile(r"(gh-issue-get\.sh)\s+[^)]+"), r"\1:*"),
    (re.compile(r"(gh-pr-detect\.sh)\s+[^)]+"), r"\1:*"),
    (re.compile(r"(generate-commit-list\.sh)\s+[^)]+"), r"\1:*"),
    (re.compile(r"(extract-session\.sh)\s+[^)]+"), r"\1:*"),
    (re.compile(r"(\.(?:sh|py))\s+[^)]+"), r"\1:*"),
    (re.compile(MKTMP_GENERALIZE_PATTERN), r"\1*"),
    (re.compile(r"(git reset --hard) origin/\S+"), r"\1"),
    (re.compile(r"(git reset --soft) [A-Fa-f0-9]{6,}"), r"\1"),
]


def generalize_permission(entry: str) -> str | None:
    original = entry
    for pattern, replacement in GENERALIZE_PATTERNS:
        entry = pattern.sub(replacement, entry)
    if entry != original:
        return entry
    return None


def _generalizations(allow_list: list[str]) -> list[tuple[str, str]]:
    existing = set(allow_list)
    replacements: list[tuple[str, str]] = []
    for entry in allow_list:
        generalized = generalize_permission(entry)
        if generalized and generalized != entry and generalized not in existing:
            replacements.append((entry, generalized))
    return replacements


def generalize_permissions(
    path: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    if not allow_list:
        return 0, []

    replacements = _generalizations(allow_list)

    if not replacements:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            live_allow = live_data.get("permissions", {}).get("allow", [])
            for old, new in _generalizations(live_allow):
                live_allow[live_allow.index(old)] = new

    messages = [f"  {old} → {new}" for old, new in replacements]
    return len(replacements), messages


def _restore(*, config_path: Path) -> int:
    from dev10x.skills.permission.backup import restore_all

    config = load_config(config_path)
    settings_files = find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    restored = restore_all(paths=settings_files)
    if not restored:
        print("No backups found to restore.")
        return 0
    for original, backup in restored:
        print(f"  Restored {original} from {backup.name}")
    print(f"\nRestored {len(restored)} files.")
    return 0


MCP_WILDCARD_PATTERN = re.compile(r"^mcp__plugin_[A-Za-z0-9]+_\*$")


def _is_nonfunctional_mcp_wildcard(rule: str) -> bool:
    return bool(MCP_WILDCARD_PATTERN.match(rule))


def _load_global_allow_rules() -> tuple[set[str], list[str]]:
    global_settings = ClaudeDir.settings_json()
    if not global_settings.is_file():
        return set(), []
    try:
        data = json.loads(global_settings.read_text())
        all_rules = data.get("permissions", {}).get("allow", [])
        wildcards = [r for r in all_rules if _is_nonfunctional_mcp_wildcard(r)]
        effective = {r for r in all_rules if not _is_nonfunctional_mcp_wildcard(r)}
        return effective, wildcards
    except (json.JSONDecodeError, OSError):
        return set(), []


def ensure_workspace_directories(
    path: Path,
    workspace_dirs: list[str],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Add missing entries to permissions.additionalDirectories.

    Allow-rules like Write(/tmp/Dev10x/**) don't cover paths outside
    the project root — Claude Code requires the directory to be
    registered as an additional working directory (GH-40). This
    function ensures the configured workspace dirs are present.

    Returns (count_added, messages).
    """
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, [f"  SKIP (invalid JSON): {e}"]

    permissions = data.get("permissions", {})
    existing = list(permissions.get("additionalDirectories", []))
    missing = [d for d in workspace_dirs if d not in existing]

    if not missing:
        return 0, []

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            if "permissions" not in live_data:
                live_data["permissions"] = {}
            current = live_data["permissions"].get("additionalDirectories", [])
            for d in workspace_dirs:
                if d not in current:
                    current.append(d)
            live_data["permissions"]["additionalDirectories"] = current

    messages = [f"  + additionalDirectories: {d}" for d in missing]
    return len(missing), messages


def _result(
    *,
    exit_code: int,
    messages: list[str],
    errors: list[str],
    total_added: int = 0,
    files_changed: int = 0,
) -> dict[str, object]:
    return {
        "exit_code": exit_code,
        "messages": messages,
        "errors": errors,
        "total_added": total_added,
        "files_changed": files_changed,
    }


def ensure_workspace(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
) -> dict[str, object]:
    """Add workspace directory registrations to settings files.

    Returns a result dict: ``{exit_code, messages, errors, total_added,
    files_changed}``. Callers print ``messages`` (stdout) and ``errors``
    (stderr) and act on ``exit_code``. No print() side effects.
    """
    messages: list[str] = []
    errors: list[str] = []

    workspace_dirs = config.get("workspace_directories", [])
    if not workspace_dirs:
        if not quiet:
            messages.append("No workspace_directories defined in config.")
        return _result(
            exit_code=0,
            messages=messages,
            errors=errors,
            total_added=0,
            files_changed=0,
        )

    if not quiet:
        messages.append(f"Workspace directories: {len(workspace_dirs)} entr(ies)")
        for d in workspace_dirs:
            messages.append(f"  - {d}")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    total_added = 0
    files_changed = 0

    for path in sorted(settings_files):
        count, file_messages = ensure_workspace_directories(
            path,
            workspace_dirs,
            dry_run=dry_run,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            files_changed += 1

    if total_added == 0:
        messages.append("All settings files already register the workspace directories.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(f"{verb} {total_added} workspace entries across {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def ensure_base(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
) -> dict[str, object]:
    """Add missing base permissions to each settings file. Returns result dict."""
    messages: list[str] = []
    errors: list[str] = []

    base_permissions = config.get("base_permissions", [])
    base_denies = config.get("base_denies", [])
    if not base_permissions and not base_denies:
        messages.append("No base_permissions or base_denies defined in config.")
        return _result(exit_code=0, messages=messages, errors=errors)

    global_rules, stale_wildcards = _load_global_allow_rules()
    filtered = [p for p in base_permissions if p not in global_rules]
    skipped = len(base_permissions) - len(filtered)

    if not quiet:
        messages.append(f"Base permissions: {len(base_permissions)} rules")
        if stale_wildcards:
            messages.append(
                f"  WARNING: {len(stale_wildcards)} non-functional MCP wildcard(s)"
                " in global settings.json:"
            )
            for wc in stale_wildcards:
                messages.append(f"    - {wc}  (Claude Code ignores MCP wildcards)")
        if skipped > 0:
            messages.append(f"  Skipping {skipped} already in global settings.json")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    if not filtered:
        if not quiet:
            messages.append("All base permissions already covered by global settings.")
        return _result(exit_code=0, messages=messages, errors=errors)

    from dev10x.skills.permission.enumerate_mcp import discover_mcp_tools

    mcp_catalog = discover_mcp_tools()

    total_added = 0
    changed_files: set[Path] = set()

    for path in sorted(settings_files):
        count, file_messages = ensure_base_permissions(
            path,
            filtered,
            dry_run=dry_run,
            mcp_catalog=mcp_catalog,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            changed_files.add(path)

    if base_denies:
        if not quiet:
            messages.append(f"\nBase denies: {len(base_denies)} rules")
        for path in sorted(settings_files):
            count, file_messages = ensure_base_denies(
                path,
                base_denies,
                dry_run=dry_run,
            )
            if count > 0:
                if not quiet:
                    messages.append(f"\n{path}")
                    messages.extend(file_messages)
                total_added += count
                changed_files.add(path)

    files_changed = len(changed_files)

    if total_added == 0:
        messages.append("All files already have base permissions.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(f"{verb} {total_added} permissions across {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def seed_worktree(
    *,
    worktree_root: Path,
    config: dict,
    dry_run: bool = False,
) -> Result[dict[str, object]]:
    """Pre-seed a single worktree's settings.local.json with base defaults (GH-602).

    A read-only surface curated once should be honored in a freshly created
    worktree without a first prompt. This seeds the worktree's
    ``.claude/settings.local.json`` (creating it when absent) with the base
    catalog, deduped against the user-global allow list. Returns the count
    added so the worktree-creation caller can report it.
    """
    base_permissions = config.get("base_permissions", [])
    base_denies = config.get("base_denies", [])
    settings = Path(worktree_root) / ".claude" / "settings.local.json"

    created_fresh = not settings.exists()
    if dry_run:
        return ok(
            {
                "path": str(settings),
                "added": 0,
                "would_create": created_fresh,
                "dry_run": True,
            }
        )

    if created_fresh:
        try:
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text("{}\n")
        except OSError as error:
            return err(f"cannot create worktree settings: {error}", path=str(settings))

    global_rules, _ = _load_global_allow_rules()
    filtered = [rule for rule in base_permissions if rule not in global_rules]

    from dev10x.skills.permission.enumerate_mcp import discover_mcp_tools

    mcp_catalog = discover_mcp_tools()
    added_allow, _ = ensure_base_permissions(settings, filtered, mcp_catalog=mcp_catalog)
    added_deny, _ = ensure_base_denies(settings, base_denies)

    return ok(
        {
            "path": str(settings),
            "added": added_allow + added_deny,
            "created_fresh": created_fresh,
        }
    )


def generalize(
    *,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
) -> dict[str, object]:
    """Replace session-specific permission args with wildcards. Returns result dict."""
    messages: list[str] = []
    errors: list[str] = []

    if dry_run and not quiet:
        messages.append("(dry run — no files will be modified)\n")

    total_generalized = 0
    files_changed = 0

    for path in sorted(settings_files):
        count, file_messages = generalize_permissions(path, dry_run=dry_run)
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_generalized += count
            files_changed += 1

    if total_generalized == 0:
        messages.append("No session-specific permissions found.")
    else:
        verb = "Would generalize" if dry_run else "Generalized"
        messages.append(f"{verb} {total_generalized} permissions in {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_generalized,
        files_changed=files_changed,
    )


def ensure_scripts(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
) -> dict[str, object]:
    """Add missing per-script allow rules for plugin scripts. Returns result dict."""
    messages: list[str] = []
    errors: list[str] = []

    cache_dir = Path(config["plugin_cache"]).expanduser()
    target_version = detect_latest_version(cache_dir)
    if not target_version:
        errors.append(f"ERROR: No versions found in {cache_dir}")
        return _result(exit_code=1, messages=messages, errors=errors)

    plugin_root = cache_dir / target_version
    scripts = scan_plugin_scripts(plugin_root)
    if not scripts:
        messages.append(f"No callable scripts found in {plugin_root}")
        return _result(exit_code=0, messages=messages, errors=errors)

    expected_rules = build_script_allow_rules(
        scripts,
        plugin_root=plugin_root,
    )

    if not quiet:
        messages.append(f"Plugin root: {plugin_root}")
        messages.append(f"Scripts found: {len(scripts)}")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    total_added = 0
    total_purged = 0
    files_changed = 0

    for path in sorted(settings_files):
        # GH-471: purge dead ** cache globs first so verify_script_coverage
        # reports the concrete version-pinned rules as missing and they get
        # added — replacing the non-functional globs rather than coexisting.
        purged, purge_messages = purge_dead_glob_script_rules(path, dry_run=dry_run)

        _covered, missing = verify_script_coverage(
            settings_path=path,
            expected_rules=expected_rules,
        )
        count = 0
        file_messages: list[str] = []
        if missing:
            count, file_messages = ensure_script_rules(
                settings_path=path,
                missing_rules=missing,
                dry_run=dry_run,
            )

        if purged > 0 or count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(purge_messages)
                messages.extend(file_messages)
            total_added += count
            total_purged += purged
            files_changed += 1

    if total_added == 0 and total_purged == 0:
        messages.append("All settings files have complete script coverage.")
    else:
        verb = "Would update" if dry_run else "Updated"
        messages.append(
            f"{verb} {files_changed} files "
            f"(+{total_added} concrete rules, -{total_purged} dead ** globs)."
        )

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def ensure_user_skill_scripts(
    *,
    settings_files: list[Path],
    skills_root: Path | None = None,
    user_home: Path | None = None,
    dry_run: bool,
    quiet: bool = False,
) -> dict[str, object]:
    """Seed canonical allow rules for user-skill scripts (GH-606 AC2).

    Enumerates ``~/.claude/skills/<dir>/scripts/*.{sh,py}`` (colon-kept and
    prefix-stripped dirs alike), emits ``~/`` + ``/home/<user>/`` twin
    ``Bash(...:*)`` rules, and SKIPS verb-blind credentialed pass-through
    wrappers so they keep prompting. Matching is exact (like
    :func:`ensure_reads`), so re-runs are idempotent.
    """
    messages: list[str] = []
    errors: list[str] = []

    root = skills_root or (ClaudeDir.home() / "skills")
    home = user_home or Path.home()
    scripts = scan_user_skill_scripts(root)
    if not scripts:
        if not quiet:
            messages.append(f"No user-skill scripts found in {root}")
        return _result(exit_code=0, messages=messages, errors=errors)

    expected_rules, skipped = build_user_skill_script_rules(
        scripts, skills_root=root, user_home=home
    )

    if not quiet:
        messages.append(f"User-skill scripts root: {root}")
        messages.append(
            f"Scripts found: {len(scripts)} ({len(expected_rules)} rules, twins included)"
        )
        for wrapper in skipped:
            messages.append(f"  SKIP (verb-blind credentialed wrapper, no :* rule): {wrapper}")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    total_added = 0
    files_changed = 0

    for path in sorted(settings_files):
        _covered, missing = verify_read_coverage(
            settings_path=path,
            expected_rules=expected_rules,
        )
        if not missing:
            continue
        count, file_messages = ensure_read_rules(
            settings_path=path,
            missing_rules=missing,
            dry_run=dry_run,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            files_changed += 1

    if total_added == 0:
        messages.append("All settings files already cover the user-skill scripts.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(
            f"{verb} {total_added} user-skill script rules across {files_changed} files."
        )

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


def ensure_reads(
    *,
    config: dict,
    settings_files: list[Path],
    dry_run: bool,
    quiet: bool = False,
) -> dict[str, object]:
    """Emit per-skill folder Read rules with ~/ + /home/<user>/ twins. Returns result dict."""
    messages: list[str] = []
    errors: list[str] = []

    cache_dir = Path(config["plugin_cache"]).expanduser()
    target_version = detect_latest_version(cache_dir)
    if not target_version:
        errors.append(f"ERROR: No versions found in {cache_dir}")
        return _result(exit_code=1, messages=messages, errors=errors)

    plugin_root = cache_dir / target_version
    expected_rules = build_read_allow_rules(
        plugin_root=plugin_root,
        user_home=Path.home(),
    )
    # GH-254: emit unversioned marketplaces Read rules alongside the
    # versioned cache rules. The runtime reads skills from the
    # marketplaces tree, which is unversioned — pinning to cache
    # versions guarantees the rule goes stale on every upgrade.
    expected_rules.extend(
        build_marketplaces_read_rules(
            plugin_cache=config["plugin_cache"],
            user_home=Path.home(),
        )
    )
    if not expected_rules:
        messages.append(f"No Read rules to emit for {plugin_root}")
        return _result(exit_code=0, messages=messages, errors=errors)

    if not quiet:
        messages.append(f"Plugin root: {plugin_root}")
        messages.append(f"Read rules expected: {len(expected_rules)} (twins included)")
        if dry_run:
            messages.append("(dry run — no files will be modified)\n")

    total_added = 0
    files_changed = 0

    for path in sorted(settings_files):
        _covered, missing = verify_read_coverage(
            settings_path=path,
            expected_rules=expected_rules,
        )
        if not missing:
            continue

        count, file_messages = ensure_read_rules(
            settings_path=path,
            missing_rules=missing,
            dry_run=dry_run,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_added += count
            files_changed += 1

    if total_added == 0:
        messages.append("All settings files have complete Read coverage.")
    else:
        verb = "Would add" if dry_run else "Added"
        messages.append(f"{verb} {total_added} Read rules across {files_changed} files.")

    return _result(
        exit_code=0,
        messages=messages,
        errors=errors,
        total_added=total_added,
        files_changed=files_changed,
    )


KNOWN_PLUGIN_DIRS = ("Dev10x", "dev10x-claude")


def _detect_plugin_cache() -> str:
    cache_root = ClaudeDir.plugins_cache_dir()
    if not cache_root.is_dir():
        return "~/.claude/plugins/cache/Dev10x-Guru/Dev10x"
    candidates: list[Path] = []
    for org_dir in cache_root.iterdir():
        if not org_dir.is_dir():
            continue
        for plugin_name in KNOWN_PLUGIN_DIRS:
            plugin_dir = org_dir / plugin_name
            if plugin_dir.is_dir():
                candidates.append(plugin_dir)
                break
    if len(candidates) == 1:
        return f"~/.claude/plugins/cache/{candidates[0].parent.name}/{candidates[0].name}"
    if len(candidates) > 1:
        names = ", ".join(f"{c.parent.name}/{c.name}" for c in candidates)
        print(f"Multiple plugin cache entries found: {names}")
        print(f"Using first match: {candidates[0].parent.name}/{candidates[0].name}")
        return f"~/.claude/plugins/cache/{candidates[0].parent.name}/{candidates[0].name}"
    return "~/.claude/plugins/cache/Dev10x-Guru/Dev10x"


def init_userspace_config() -> dict[str, object]:
    """Create or migrate the userspace projects config (GH-577).

    Consolidates on ``projects.yaml`` (MEMORY_CONFIG). When only the
    legacy ``upgrade-cleanup-projects.yaml`` (USERSPACE_CONFIG) exists,
    its content is migrated into ``projects.yaml`` so ``clean`` and
    ``merge-worktree`` — which now read ``projects.yaml`` — see the same
    roots as every other subcommand. The legacy file is left in place
    for downgrade safety; ``upgrade-cleanup``/``plugin-doctor`` remove
    it once parity is confirmed. Returns a result dict.
    """
    from dev10x.domain.file_locks import atomic_write_text, file_lock

    messages: list[str] = []
    errors: list[str] = []

    if MEMORY_CONFIG.is_file():
        messages.append(f"Config already exists: {MEMORY_CONFIG}")
        return _result(exit_code=0, messages=messages, errors=errors)

    MEMORY_CONFIG.parent.mkdir(parents=True, exist_ok=True)

    # Double-checked locking (GH-587): two worktrees/agents racing first-call
    # init must not both pass the exists-check and clobber each other's write.
    with file_lock(MEMORY_CONFIG):
        if MEMORY_CONFIG.is_file():
            messages.append(f"Config already exists: {MEMORY_CONFIG}")
            return _result(exit_code=0, messages=messages, errors=errors)

        if USERSPACE_CONFIG.is_file():
            atomic_write_text(MEMORY_CONFIG, USERSPACE_CONFIG.read_text())
            messages.append(f"Migrated {USERSPACE_CONFIG} -> {MEMORY_CONFIG}")
            messages.append(f"{USERSPACE_CONFIG} is deprecated; edit {MEMORY_CONFIG} from now on.")
            return _result(exit_code=0, messages=messages, errors=errors)

        if not PLUGIN_CONFIG.is_file():
            errors.append(f"ERROR: Plugin default config not found: {PLUGIN_CONFIG}")
            return _result(exit_code=1, messages=messages, errors=errors)

        content = PLUGIN_CONFIG.read_text()
        detected_cache = _detect_plugin_cache()
        content = content.replace(
            "~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude",
            detected_cache,
        )
        atomic_write_text(MEMORY_CONFIG, content)
        messages.append(f"Created: {MEMORY_CONFIG}")
        messages.append(f"Plugin cache: {detected_cache}")
        messages.append("Edit this file to add your project roots.")
        return _result(exit_code=0, messages=messages, errors=errors)
