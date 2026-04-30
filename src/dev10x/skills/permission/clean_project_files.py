"""Clean redundant permission rules from project settings.local.json files.

Compares project-level allow rules against global ~/.claude/settings.json
and strips rules that are:
  - Exact duplicates of global rules
  - Covered by global wildcard patterns (MCP families, plugin path wildcards)
  - Old plugin version paths (any version older than current)
  - Env-prefixed session noise (GIT_SEQUENCE_EDITOR=*, DATABASE_URL=*, etc.)
  - Shell control flow fragments (do, done, fi, for, while, etc.)
  - Double-slash path typos (Read(//...), Write(//...))

Also flags rules containing leaked secrets (env vars with plaintext values).

CLI entry point: ``dev10x permission clean``.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

USERSPACE_CONFIG = (
    Path.home() / ".claude" / "skills" / "Dev10x:upgrade-cleanup" / "projects.yaml"
)
PLUGIN_CONFIG = (
    Path(__file__).resolve().parents[4] / "skills" / "upgrade-cleanup" / "projects.yaml"
)
GLOBAL_SETTINGS = Path.home() / ".claude" / "settings.json"

PLUGIN_NAMES = r"(?:Dev10x|dev10x(?:-claude)?)"
VERSION_PATTERN = re.compile(
    rf"plugins/cache/[^/]+/{PLUGIN_NAMES}/(\d+\.\d+\.\d+)", re.IGNORECASE
)
PUBLISHER_PATTERN = re.compile(rf"plugins/cache/([^/]+)/{PLUGIN_NAMES}/", re.IGNORECASE)

ENV_PREFIX_PATTERN = re.compile(r"^Bash\([A-Z_]+=")

SHELL_FRAGMENTS = frozenset(
    {
        "do",
        "done",
        "fi",
        "for",
        "while",
        "break",
        "then",
        "else",
        "if",
        "case",
        "esac",
        "select",
        "until",
    }
)

DOUBLE_SLASH_PATTERN = re.compile(r"\(//")

# Patterns superseded by ensure-reads per-skill enumeration (GH-48).
# The `Read(...Dev10x/*/**)` glob does not reliably match in Claude
# Code's permission engine — keep the deprecated rule list narrow and
# explicit so future deprecations stay searchable.
DEPRECATED_READ_GLOBS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^Read\((?:~|/home/[^/]+)/\.claude/plugins/cache/[^/]+/"
        rf"{PLUGIN_NAMES}/\*/\*\*\)$",
        re.IGNORECASE,
    ),
)


def is_deprecated_read_glob(rule: str) -> bool:
    return any(p.match(rule) for p in DEPRECATED_READ_GLOBS)


HOOK_ENABLED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^Bash\(gh pr create"),
    re.compile(r"^Bash\(git push"),
    re.compile(r"^Bash\(git rebase -i"),
    re.compile(r"^Bash\(git commit -m"),
    re.compile(r"^Bash\(gh pr checks"),
]

SECRET_INDICATORS = [
    re.compile(r"LINEAR_KEY=lin_api_"),
    re.compile(r"DATABASE_URL=postgres"),
    re.compile(r"SECRET_KEY=\S"),
    re.compile(r"API_KEY=\S"),
    re.compile(r"TOKEN=\S{10,}"),
    re.compile(r"PASSWORD=\S"),
    re.compile(r"PRIVATE_KEY=\S"),
]


WILDCARD_BYPASS_PATTERNS = [
    re.compile(r"^Bash\(\*\)$"),
    re.compile(r"^Bash\(\.\*\)$"),
    re.compile(r"^Read\(\*\)$"),
    re.compile(r"^Write\(\*\)$"),
    re.compile(r"^Edit\(\*\)$"),
]


@dataclass
class RemovalResult:
    exact_duplicates: list[str] = field(default_factory=list)
    old_versions: list[str] = field(default_factory=list)
    stale_publisher: list[str] = field(default_factory=list)
    env_noise: list[str] = field(default_factory=list)
    shell_fragments: list[str] = field(default_factory=list)
    double_slash: list[str] = field(default_factory=list)
    leaked_secrets: list[str] = field(default_factory=list)
    hook_enabled: list[str] = field(default_factory=list)
    wildcard_bypasses: list[str] = field(default_factory=list)
    allow_deny_contradictions: list[tuple[str, str]] = field(default_factory=list)
    ask_shadowed_by_allow: list[tuple[str, str]] = field(default_factory=list)
    deprecated_globs: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    @property
    def total_removed(self) -> int:
        return (
            len(self.exact_duplicates)
            + len(self.old_versions)
            + len(self.stale_publisher)
            + len(self.env_noise)
            + len(self.shell_fragments)
            + len(self.double_slash)
            + len(self.deprecated_globs)
        )


def find_config() -> Path:
    if USERSPACE_CONFIG.is_file():
        return USERSPACE_CONFIG
    if PLUGIN_CONFIG.is_file():
        return PLUGIN_CONFIG
    print(
        f"ERROR: No config found. Create {USERSPACE_CONFIG}\nor ensure {PLUGIN_CONFIG} exists.",
        file=sys.stderr,
    )
    sys.exit(1)


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_global_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def extract_allow_rules(data: dict) -> set[str]:
    return set(data.get("permissions", {}).get("allow", []))


def detect_current_version(cache_dir: Path) -> str | None:
    if not cache_dir.is_dir():
        return None
    versions = sorted(
        cache_dir.iterdir(),
        key=lambda p: _version_tuple(p.name),
    )
    return versions[-1].name if versions else None


def _version_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in version.split("."))
    except ValueError:
        return (0,)


def is_shell_fragment(rule: str) -> bool:
    match = re.match(r"^Bash\((\w+)\b", rule)
    if match:
        return match.group(1) in SHELL_FRAGMENTS
    return False


def is_stale_publisher(
    rule: str,
    *,
    cache_root: Path | None,
) -> bool:
    if cache_root is None:
        return False
    match = PUBLISHER_PATTERN.search(rule)
    if not match:
        return False
    publisher = match.group(1)
    return not (cache_root / publisher).is_dir()


def is_old_version(
    rule: str,
    current_version: str | None,
) -> bool:
    if current_version is None:
        return False
    match = VERSION_PATTERN.search(rule)
    if not match:
        return False
    rule_version = match.group(1)
    return _version_tuple(rule_version) < _version_tuple(current_version)


def is_hook_enabled(rule: str) -> bool:
    return any(p.search(rule) for p in HOOK_ENABLED_PATTERNS)


def has_leaked_secret(rule: str) -> bool:
    return any(p.search(rule) for p in SECRET_INDICATORS)


def is_wildcard_bypass(rule: str) -> bool:
    return any(p.match(rule) for p in WILDCARD_BYPASS_PATTERNS)


def find_allow_deny_contradictions(
    allow_rules: list[str],
    deny_rules: list[str],
) -> list[tuple[str, str]]:
    contradictions: list[tuple[str, str]] = []
    for allow in allow_rules:
        for deny in deny_rules:
            if allow == deny:
                contradictions.append((allow, deny))
    return contradictions


def find_ask_shadowed_by_allow(
    allow_rules: list[str],
    ask_rules: list[str],
) -> list[tuple[str, str]]:
    shadowed: list[tuple[str, str]] = []
    for ask in ask_rules:
        for allow in allow_rules:
            if allow == ask:
                shadowed.append((ask, allow))
                break
            if "*" in allow:
                pattern = re.escape(allow).replace(r"\*", ".*")
                if re.fullmatch(pattern, ask):
                    shadowed.append((ask, allow))
                    break
    return shadowed


def classify_rules(
    project_rules: list[str],
    *,
    global_rules: set[str],
    current_version: str | None,
    base_permissions: set[str] | None = None,
    cache_root: Path | None = None,
    deny_rules: list[str] | None = None,
    ask_rules: list[str] | None = None,
) -> RemovalResult:
    result = RemovalResult()
    _base = base_permissions or set()

    if deny_rules:
        result.allow_deny_contradictions = find_allow_deny_contradictions(
            allow_rules=project_rules,
            deny_rules=deny_rules,
        )

    if ask_rules:
        result.ask_shadowed_by_allow = find_ask_shadowed_by_allow(
            allow_rules=project_rules,
            ask_rules=ask_rules,
        )

    for rule in project_rules:
        if has_leaked_secret(rule):
            result.leaked_secrets.append(rule)

        if is_wildcard_bypass(rule):
            result.wildcard_bypasses.append(rule)

        if rule in _base:
            result.kept.append(rule)
            continue

        if is_hook_enabled(rule):
            result.hook_enabled.append(rule)
            result.kept.append(rule)
            continue

        if rule in global_rules:
            result.exact_duplicates.append(rule)
            continue

        if is_stale_publisher(rule, cache_root=cache_root):
            result.stale_publisher.append(rule)
            continue

        if is_old_version(rule, current_version):
            result.old_versions.append(rule)
            continue

        if ENV_PREFIX_PATTERN.search(rule):
            result.env_noise.append(rule)
            continue

        if is_shell_fragment(rule):
            result.shell_fragments.append(rule)
            continue

        if DOUBLE_SLASH_PATTERN.search(rule):
            result.double_slash.append(rule)
            continue

        if is_deprecated_read_glob(rule):
            result.deprecated_globs.append(rule)
            continue

        result.kept.append(rule)

    return result


def clean_file(
    path: Path,
    *,
    global_rules: set[str],
    current_version: str | None,
    base_permissions: set[str] | None = None,
    cache_root: Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[RemovalResult | None, list[str]]:
    content = path.read_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return None, [f"  SKIP (invalid JSON): {e}"]

    perms = data.get("permissions", {})
    allow_list: list[str] = perms.get("allow", [])
    deny_list: list[str] = perms.get("deny", [])
    ask_list: list[str] = perms.get("ask", [])

    if not allow_list:
        return RemovalResult(), []

    result = classify_rules(
        allow_list,
        global_rules=global_rules,
        current_version=current_version,
        base_permissions=base_permissions,
        cache_root=cache_root,
        deny_rules=deny_list if deny_list else None,
        ask_rules=ask_list if ask_list else None,
    )

    has_findings = (
        result.total_removed > 0
        or result.wildcard_bypasses
        or result.allow_deny_contradictions
        or result.ask_shadowed_by_allow
    )
    if not has_findings:
        return result, []

    if not dry_run and result.total_removed > 0:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live_data:
            live_data["permissions"]["allow"] = result.kept

    messages = _format_messages(result, verbose=verbose)
    return result, messages


def _format_messages(
    result: RemovalResult,
    *,
    verbose: bool = False,
) -> list[str]:
    messages: list[str] = []

    if result.leaked_secrets:
        messages.append(f"  ⚠ LEAKED SECRETS ({len(result.leaked_secrets)}):")
        for rule in result.leaked_secrets:
            messages.append(f"    ⚠ {rule}")

    if result.wildcard_bypasses:
        messages.append(f"  ⚠ WILDCARD BYPASSES ({len(result.wildcard_bypasses)}):")
        for rule in result.wildcard_bypasses:
            messages.append(f"    ⚠ {rule}")

    if result.allow_deny_contradictions:
        messages.append(
            f"  ⚠ ALLOW/DENY CONTRADICTIONS ({len(result.allow_deny_contradictions)}):"
        )
        for allow, deny in result.allow_deny_contradictions:
            messages.append(f"    allow: {allow}")
            messages.append(f"    deny:  {deny}")

    if result.ask_shadowed_by_allow:
        messages.append(
            f"  ⚠ ASK SHADOWED BY ALLOW ({len(result.ask_shadowed_by_allow)}):"
        )
        for ask, allow in result.ask_shadowed_by_allow:
            messages.append(f"    ask:   {ask}")
            messages.append(f"    allow: {allow}")

    if result.exact_duplicates:
        messages.append(
            f"  - {len(result.exact_duplicates)} exact duplicates of global rules"
        )
        if verbose:
            for rule in result.exact_duplicates:
                messages.append(f"    {rule}")

    if result.old_versions:
        messages.append(f"  - {len(result.old_versions)} old plugin versions")
        if verbose:
            for rule in result.old_versions:
                messages.append(f"    {rule}")

    if result.stale_publisher:
        messages.append(f"  - {len(result.stale_publisher)} stale publisher paths")
        if verbose:
            for rule in result.stale_publisher:
                messages.append(f"    {rule}")

    if result.env_noise:
        messages.append(f"  - {len(result.env_noise)} env-prefixed session noise")
        if verbose:
            for rule in result.env_noise:
                messages.append(f"    {rule}")

    if result.shell_fragments:
        messages.append(
            f"  - {len(result.shell_fragments)} shell control flow fragments"
        )
        if verbose:
            for rule in result.shell_fragments:
                messages.append(f"    {rule}")

    if result.double_slash:
        messages.append(f"  - {len(result.double_slash)} double-slash paths")
        if verbose:
            for rule in result.double_slash:
                messages.append(f"    {rule}")

    if result.deprecated_globs:
        messages.append(
            f"  - {len(result.deprecated_globs)} deprecated Read globs"
            " (superseded by ensure-reads)"
        )
        if verbose:
            for rule in result.deprecated_globs:
                messages.append(f"    {rule}")

    if result.hook_enabled:
        messages.append(f"  - {len(result.hook_enabled)} hook-enabled rules (kept)")
        if verbose:
            for rule in result.hook_enabled:
                messages.append(f"    {rule}")

    messages.append(f"  Removed: {result.total_removed} | Kept: {len(result.kept)}")
    return messages


def find_settings_files(roots: list[str]) -> list[Path]:
    files: list[Path] = []

    project_settings_dir = Path.home() / ".claude" / "projects"
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


def _restore(*, config_path: Path) -> int:
    from dev10x.skills.permission.backup import restore_all

    config = load_config(config_path)
    settings_files = find_settings_files(roots=config.get("roots", []))
    restored = restore_all(paths=settings_files)
    if not restored:
        print("No backups found to restore.")
        return 0
    for original, backup in restored:
        print(f"  Restored {original} from {backup.name}")
    print(f"\nRestored {len(restored)} files.")
    return 0
