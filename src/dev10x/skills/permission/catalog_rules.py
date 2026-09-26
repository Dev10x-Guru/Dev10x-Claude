"""Compute the permission rules the catalog expects — no writes (GH-1432).

Everything here answers "which rule should exist?" or "does this rule
cover that?": scanning plugin and user-skill scripts, building the Bash
and Read rules for them, checking a settings file's coverage, collapsing
retired upgrade-cleanup rules, and generalizing session-specific
arguments. The writers in :mod:`dev10x.skills.permission.catalog_write`
act on these answers. Split out of ``update_paths.py`` by GH-1432.
"""

import json
import re
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.mktmp_path import MKTMP_GENERALIZE_PATTERN
from dev10x.skills.permission.catalog_load import extract_cache_publisher

MCP_WILDCARD_PATTERN = re.compile(r"^mcp__plugin_[A-Za-z0-9]+_\*$")


def _is_nonfunctional_mcp_wildcard(rule: str) -> bool:
    return bool(MCP_WILDCARD_PATTERN.match(rule))


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


_DUP_SLASH_RE = re.compile(r"(?<!:)/{2,}")


def collapse_double_slashes(path: str) -> str:
    """Collapse runs of ``/`` to a single ``/`` without touching ``://``.

    ``${CLAUDE_PLUGIN_ROOT}`` resolves with a trailing slash, so a naive
    ``f"{root}/{rel}"`` join yields ``.../<ver>//skills/...`` (GH-704). The
    verbatim permission matcher treats ``//`` ≠ ``/``, so such a rule never
    matches. Normalizing at the rule-generation source guarantees we never
    emit a ``//`` that the matcher would silently reject. The ``(?<!:)``
    guard preserves scheme separators like ``mcp://`` untouched.
    """
    return _DUP_SLASH_RE.sub("/", path)


def build_script_allow_rules(
    scripts: list[Path],
    *,
    plugin_root: Path,
) -> list[str]:
    rules: list[str] = []
    for script in scripts:
        relative = script.relative_to(plugin_root)
        body = collapse_double_slashes(f"{plugin_root}/{relative}")
        rules.append(str(AllowRule.bash(f"{body}:*")))
    return rules


def build_marketplaces_script_rules(
    scripts: list[Path],
    *,
    plugin_root: Path,
    plugin_cache: str,
    user_home: Path,
) -> list[str]:
    """Emit unversioned marketplace-root Bash rules for plugin scripts (GH-704).

    :func:`build_script_allow_rules` pins the versioned ``cache/<ver>/``
    dispatch root, but the runtime also dispatches skill scripts from the
    unversioned ``marketplaces/<publisher>/`` root. A grant for one root
    family never matches the other (GH-488 evidence #31), so a cache-pinned
    rule leaves marketplace-dispatched scripts re-prompting forever.

    This mirrors :func:`build_marketplaces_read_rules` for the Bash
    skill-script scope: for each script, emit ``~/`` and ``/home/<user>/``
    twins anchored at ``marketplaces/<publisher>/<relative>`` so a grant
    matches whichever root family dispatches the script. ``relative`` is the
    same sub-path in both layouts (``skills/<name>/scripts/<file>`` etc.).
    """
    publisher = extract_cache_publisher(plugin_cache)
    if not publisher:
        return []

    home = user_home.expanduser().resolve()
    rel_root = f".claude/plugins/marketplaces/{publisher}"
    rules: list[str] = []
    for script in scripts:
        relative = script.relative_to(plugin_root)
        tilde = collapse_double_slashes(f"~/{rel_root}/{relative}")
        absolute = collapse_double_slashes(f"{home}/{rel_root}/{relative}")
        rules.append(str(AllowRule.bash(f"{tilde}:*")))
        rules.append(str(AllowRule.bash(f"{absolute}:*")))
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
        parsed = AllowRule.parse(rule)
        if parsed.tool != "Bash" or not parsed.inner.endswith(":*"):
            missing.append(rule)
            continue
        script_name = Path(parsed.inner[: -len(":*")]).name
        # GH-471: a ** cache glob never matches in Claude Code's Bash
        # matcher and update-paths cannot re-version it (no literal X.Y.Z
        # segment), so it is NOT real coverage. Skip dead globs here so a
        # concrete version-pinned rule is emitted instead.
        if rule in allow_list or any(
            _entry_covers_script(entry, script_name)
            for entry in allow_list
            if not is_dead_glob_script_rule(entry)
        ):
            covered.append(rule)
        else:
            missing.append(rule)
    return covered, missing


def _entry_covers_script(entry: str, script_name: str) -> bool:
    """Whether ``entry`` is a ``Bash(.../<script_name>:*)`` coverage rule."""
    parsed = AllowRule.parse(entry)
    if parsed.tool != "Bash" or not parsed.inner.endswith(":*"):
        return False
    return parsed.inner[: -len(":*")].endswith("/" + script_name)


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


# GH-1150: an argument tail can legitimately contain escaped parens —
# a BigQuery predicate like `JSON_VALUE\(c,'$.k'\)` is the observed case.
# A bare `[^)]+` stops at the first `\)`, so the substitution closed the
# rule early and stranded the remainder outside it, yielding a malformed
# string like `Bash(/tmp/q.py:*)" | tail -20)`. Claude Code silently
# drops an invalid rule on the next read, so a working (if over-specific)
# allow rule was destroyed and the run reported success. Consume escaped
# parens as payload and stop only at an unescaped `)`.
#
# The escape branch MUST precede the any-char branch: `[^)]` happily
# matches a lone backslash, and once it has consumed the `\` of a `\)`
# the escape branch can no longer see it, leaving the match stranded at
# the very paren this is meant to step over.
_RULE_ARG_TAIL = r"(?:\\.|[^)])+"

GENERALIZE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(detect-tracker\.sh)\s+" + _RULE_ARG_TAIL), r"\1:*"),
    (re.compile(r"(gh-issue-get\.sh)\s+" + _RULE_ARG_TAIL), r"\1:*"),
    (re.compile(r"(gh-pr-detect\.sh)\s+" + _RULE_ARG_TAIL), r"\1:*"),
    (re.compile(r"(generate-commit-list\.sh)\s+" + _RULE_ARG_TAIL), r"\1:*"),
    (re.compile(r"(extract-session\.sh)\s+" + _RULE_ARG_TAIL), r"\1:*"),
    (re.compile(r"(\.(?:sh|py))\s+" + _RULE_ARG_TAIL), r"\1:*"),
    (re.compile(MKTMP_GENERALIZE_PATTERN), r"\1*"),
    (re.compile(r"(git reset --hard) origin/\S+"), r"\1"),
    (re.compile(r"(git reset --soft) [A-Fa-f0-9]{6,}"), r"\1"),
]

_RULE_SHAPE_RE = re.compile(r"^[A-Za-z]+\(.*\)$", re.DOTALL)


def _unescaped_parens_balance(entry: str) -> bool:
    """True when `entry`'s unescaped parens nest and close cleanly."""
    depth = 0
    index = 0
    while index < len(entry):
        char = entry[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0


def is_well_formed_rule(entry: str) -> bool:
    """True when `entry` is a syntactically valid permission rule (GH-1150).

    Guards the generalizer's output. An emitted rule that fails this
    check is not a cosmetic problem: the permission engine discards it
    without comment, so writing one deletes the over-specific rule the
    user actually had and reports a successful generalization.
    """
    if not _RULE_SHAPE_RE.match(entry):
        return False
    return _unescaped_parens_balance(entry)


def generalize_permission(entry: str) -> str | None:
    original = entry
    for pattern, replacement in GENERALIZE_PATTERNS:
        entry = pattern.sub(replacement, entry)
    if entry != original:
        return entry
    return None


def _generalizations(allow_list: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Return the safe (old, new) rewrites plus the rules it refused to touch."""
    existing = set(allow_list)
    replacements: list[tuple[str, str]] = []
    refused: list[str] = []
    for entry in allow_list:
        generalized = generalize_permission(entry)
        if not generalized or generalized == entry or generalized in existing:
            continue
        if not is_well_formed_rule(generalized):
            refused.append(entry)
            continue
        replacements.append((entry, generalized))
    return replacements, refused
