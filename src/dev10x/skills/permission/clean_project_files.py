"""Clean redundant permission rules from project settings.local.json files.

Compares project-level allow rules against global ~/.claude/settings.json
and strips rules that are:
  - Exact string duplicates of global rules (see WARNING below)
  - Old plugin version paths (any version older than current)
  - Env-prefixed session noise (GIT_SEQUENCE_EDITOR=*, DATABASE_URL=*, etc.)
  - Shell control flow fragments (do, done, fi, for, while, etc.)
  - Double-slash path typos (Read(//...), Write(//...))

Also flags rules containing leaked secrets: env-var key/value pairs, known
token prefixes (GitHub, GitLab, AWS), Bearer headers, and URL query-string
tokens. Findings name the matched rule (with the credential VALUE redacted),
the matched pattern, and the redacted span — never the raw secret (GH-1312).

WARNING — global-dedup assumption (#47):
  The exact-duplicate removal assumes global ~/.claude/settings.json rules
  are reliably inherited into every project that has its own
  settings.local.json.  Empirical evidence (#47, closed by #50) shows this
  is NOT always true: when a project has its own settings.local.json, the
  local file appears to win and global rules are not always inherited.
  Removing a project rule solely because it duplicates a global rule can
  therefore reintroduce per-invocation permission prompts for that project.
  Use ``--skip-global-dedup`` (or ``skip_global_dedup=True`` in code) to
  preserve project-local copies of global rules when you need certainty.

CLI entry point: ``dev10x permission clean``.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.plugin_version import SEMVER_PATTERN, PluginVersion
from dev10x.domain.common.result import Result
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.plugin_identity import PLUGIN_NAMES
from dev10x.skills.permission.catalog_paths import shipped_projects_catalog
from dev10x.skills.permission.config import parse_config, resolve_config

MEMORY_CONFIG = Dev10xConfigDir.projects_yaml()
USERSPACE_CONFIG = Dev10xConfigDir.upgrade_cleanup_projects_yaml()
PLUGIN_CONFIG = shipped_projects_catalog()
GLOBAL_SETTINGS = ClaudeDir.settings_json()

VERSION_PATTERN = re.compile(
    rf"plugins/cache/[^/]+/{PLUGIN_NAMES}/({SEMVER_PATTERN})", re.IGNORECASE
)
PUBLISHER_PATTERN = re.compile(rf"plugins/cache/([^/]+)/{PLUGIN_NAMES}/", re.IGNORECASE)

_ENV_PREFIX_INNER_RE = re.compile(r"^[A-Z_]+=")

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


HOOK_ENABLED_INNER_PREFIXES: tuple[str, ...] = (
    "gh pr create",
    "git push",
    "git rebase -i",
    "git commit -m",
    "gh pr checks",
)


@dataclass(frozen=True)
class SecretPattern:
    """A named credential-shape detector (GH-1312).

    ``pattern`` MUST define a ``secret`` capture group spanning only the
    credential *value* — the part redacted before any user-facing output —
    so a matched rule such as ``API_KEY=...`` keeps the ``API_KEY=`` prefix
    visible while the value itself never reaches a message, log, or commit.
    """

    rule_id: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class LeakedSecretFinding:
    """One matched credential shape, safe to print (GH-1312).

    ``redacted_rule`` is the original rule string with only the matched
    ``secret`` span replaced by a placeholder — never the raw value.
    ``span`` names the character offsets of the redacted value within the
    ORIGINAL rule string, so a maintainer can locate the finding in the
    settings file without the payload ever being echoed.
    """

    rule_id: str
    redacted_rule: str
    span: tuple[int, int]


# Credential *shapes*, not bare word matches — a filename like
# `html-token-validator.py` or an env var name with no value attached must
# never match (GH-1312). Each pattern's `secret` group is the minimal span
# that identifies the actual credential value so redaction can mask only
# that portion, leaving the rest of the rule (and any `<KEY>=` prefix)
# visible for triage.
SECRET_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern("linear-api-key", re.compile(r"LINEAR_KEY=(?P<secret>lin_api_\S+)")),
    SecretPattern("database-url", re.compile(r"DATABASE_URL=(?P<secret>postgres\S+)")),
    SecretPattern("secret-key-env", re.compile(r"SECRET_KEY=(?P<secret>\S+)")),
    SecretPattern("api-key-env", re.compile(r"API_KEY=(?P<secret>\S+)")),
    SecretPattern("token-env", re.compile(r"TOKEN=(?P<secret>\S{10,})")),
    SecretPattern("password-env", re.compile(r"PASSWORD=(?P<secret>\S+)")),
    SecretPattern("private-key-env", re.compile(r"PRIVATE_KEY=(?P<secret>\S+)")),
    # GitHub token prefixes: ghp_ (PAT), gho_ (OAuth), ghu_ (user-to-server),
    # ghs_ (server-to-server), ghr_ (refresh).
    SecretPattern("github-token", re.compile(r"(?P<secret>gh[oprsu]_[A-Za-z0-9]{20,})")),
    SecretPattern("gitlab-token", re.compile(r"(?P<secret>glpat-[A-Za-z0-9_-]{20,})")),
    SecretPattern("aws-access-key-id", re.compile(r"(?P<secret>AKIA[0-9A-Z]{16})")),
    SecretPattern(
        "bearer-header",
        re.compile(r"Bearer\s+(?P<secret>[A-Za-z0-9\-._~+/]{16,}=*)"),
    ),
    # A capability token embedded in a URL query string, e.g. an invoice
    # link of the form `...?token=<uuid>` (GH-1312 repro) — the false
    # negative that let a real credential slip past `generalize` unflagged.
    SecretPattern(
        "url-token-param",
        re.compile(r"[?&]token=(?P<secret>[A-Za-z0-9\-_]{8,})", re.IGNORECASE),
    ),
)

_REDACTED = "<redacted>"


_WILDCARD_BYPASS_TOOLS: dict[str, frozenset[str]] = {
    "Bash": frozenset({"*", ".*"}),
    "Read": frozenset({"*"}),
    "Write": frozenset({"*"}),
    "Edit": frozenset({"*"}),
}


@dataclass
class RemovalResult:
    exact_duplicates: list[str] = field(default_factory=list)
    old_versions: list[str] = field(default_factory=list)
    stale_publisher: list[str] = field(default_factory=list)
    env_noise: list[str] = field(default_factory=list)
    shell_fragments: list[str] = field(default_factory=list)
    double_slash: list[str] = field(default_factory=list)
    leaked_secrets: list[LeakedSecretFinding] = field(default_factory=list)
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


def find_config() -> Result[Path]:
    candidates = [MEMORY_CONFIG, USERSPACE_CONFIG]
    if PLUGIN_CONFIG is not None:
        candidates.append(PLUGIN_CONFIG)
    return resolve_config(candidates=candidates, create_path=MEMORY_CONFIG)


def load_config(config_path: Path) -> dict:
    return parse_config(config_path)


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
        key=lambda p: PluginVersion.sort_key(p.name),
    )
    return versions[-1].name if versions else None


def is_shell_fragment(rule: str) -> bool:
    match = re.match(r"^Bash\((\w+)\b", rule)
    if match:
        return match.group(1) in SHELL_FRAGMENTS
    return False


def is_env_noise(rule: str) -> bool:
    parsed = AllowRule.parse(rule)
    return parsed.tool == "Bash" and _ENV_PREFIX_INNER_RE.match(parsed.inner) is not None


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
    rule_version = PluginVersion.try_parse(match.group(1))
    current = PluginVersion.try_parse(current_version)
    if rule_version is None or current is None:
        return False
    return rule_version < current


def is_hook_enabled(rule: str) -> bool:
    parsed = AllowRule.parse(rule)
    return parsed.tool == "Bash" and any(
        parsed.inner.startswith(prefix) for prefix in HOOK_ENABLED_INNER_PREFIXES
    )


def find_leaked_secret(rule: str) -> LeakedSecretFinding | None:
    """Return the first matched credential shape in ``rule``, or ``None``.

    The returned finding carries a redacted rule string — the secret VALUE
    itself is never retained or returned (GH-1312).
    """
    for secret_pattern in SECRET_PATTERNS:
        match = secret_pattern.pattern.search(rule)
        if match is None:
            continue
        start, end = match.span("secret")
        redacted_rule = f"{rule[:start]}{_REDACTED}{rule[end:]}"
        return LeakedSecretFinding(
            rule_id=secret_pattern.rule_id,
            redacted_rule=redacted_rule,
            span=(start, end),
        )
    return None


def has_leaked_secret(rule: str) -> bool:
    return find_leaked_secret(rule) is not None


def is_wildcard_bypass(rule: str) -> bool:
    parsed = AllowRule.parse(rule)
    return parsed.inner in _WILDCARD_BYPASS_TOOLS.get(parsed.tool, frozenset())


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
    skip_global_dedup: bool = False,
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
        finding = find_leaked_secret(rule)
        if finding is not None:
            result.leaked_secrets.append(finding)

        if is_wildcard_bypass(rule):
            result.wildcard_bypasses.append(rule)

        if rule in _base:
            result.kept.append(rule)
            continue

        if is_hook_enabled(rule):
            result.hook_enabled.append(rule)
            result.kept.append(rule)
            continue

        if not skip_global_dedup and rule in global_rules:
            result.exact_duplicates.append(rule)
            continue

        if is_stale_publisher(rule, cache_root=cache_root):
            result.stale_publisher.append(rule)
            continue

        if is_old_version(rule, current_version):
            result.old_versions.append(rule)
            continue

        if is_env_noise(rule):
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
    skip_global_dedup: bool = False,
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
        skip_global_dedup=skip_global_dedup,
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
        for finding in result.leaked_secrets:
            start, end = finding.span
            messages.append(
                f"    ⚠ [{finding.rule_id}] {finding.redacted_rule} (redacted chars {start}-{end})"
            )

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
        messages.append(f"  ⚠ ASK SHADOWED BY ALLOW ({len(result.ask_shadowed_by_allow)}):")
        for ask, allow in result.ask_shadowed_by_allow:
            messages.append(f"    ask:   {ask}")
            messages.append(f"    allow: {allow}")

    if result.exact_duplicates:
        messages.append(f"  - {len(result.exact_duplicates)} exact duplicates of global rules")
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
        messages.append(f"  - {len(result.shell_fragments)} shell control flow fragments")
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


@dataclass(frozen=True)
class CleanFileOutcome:
    """One settings file's clean-file result plus its rendered messages.

    ``result`` is ``None`` when the file could not be cleaned at all
    (mirrors :func:`clean_file`'s own ``None`` case) — ``messages`` then
    carries the reason and no totals are aggregated for this file.
    """

    path: Path
    messages: list[str]
    result: RemovalResult | None

    @property
    def has_findings(self) -> bool:
        if self.result is None:
            return False
        return bool(
            self.result.total_removed > 0
            or self.result.leaked_secrets
            or self.result.wildcard_bypasses
            or self.result.allow_deny_contradictions
            or self.result.ask_shadowed_by_allow
        )


@dataclass
class CleanRunResult:
    """Aggregated outcome of cleaning every settings file in one run (GH-1442).

    Extracted from ``commands/permission.py::clean()``, which used to
    carry ~110 lines of loop-and-aggregate logic inline in the Click
    handler — the least testable command in that file, unlike
    ``merge_worktree`` and ``ensure_ignored`` which already delegate
    their multi-file loops to the skill module. The Click handler now
    only formats and prints this result.
    """

    outcomes: list[CleanFileOutcome] = field(default_factory=list)
    total_removed: int = 0
    total_kept: int = 0
    files_changed: int = 0
    total_secrets: int = 0
    total_global_dedup: int = 0


def run_clean(
    *,
    settings_files: list[Path],
    global_rules: set[str],
    current_version: str | None,
    base_permissions: set[str],
    cache_root: Path | None,
    dry_run: bool,
    verbose: bool,
    skip_global_dedup: bool,
) -> CleanRunResult:
    """Clean every settings file and aggregate the totals."""
    run = CleanRunResult()
    for path in sorted(settings_files):
        result, messages = clean_file(
            path,
            global_rules=global_rules,
            current_version=current_version,
            base_permissions=base_permissions,
            cache_root=cache_root,
            dry_run=dry_run,
            verbose=verbose,
            skip_global_dedup=skip_global_dedup,
        )
        outcome = CleanFileOutcome(path=path, messages=messages, result=result)
        run.outcomes.append(outcome)
        if result is None:
            continue
        if outcome.has_findings:
            run.total_removed += result.total_removed
            run.total_kept += len(result.kept)
            run.total_secrets += len(result.leaked_secrets)
            run.total_global_dedup += len(result.exact_duplicates)
            if result.total_removed > 0:
                run.files_changed += 1
        else:
            run.total_kept += len(result.kept)
    return run


def _restore(*, config_path: Path) -> int:
    from dev10x.skills.permission.backup import restore_report

    config = load_config(config_path)
    settings_files = find_settings_files(roots=config.get("roots", []))
    code, report = restore_report(paths=settings_files)
    print(report)
    return code
