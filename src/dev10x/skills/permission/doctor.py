"""Permission doctor — diagnose and fix common allow-rule friction (GH-99).

Three concerns this module addresses:

1. **Duplicate-slash path typos** — ``${CLAUDE_PLUGIN_ROOT}`` expands with a
   trailing slash, so an expanded rule can bake a literal ``//`` into
   ``settings`` (e.g. ``.../<ver>//skills/...``); the verbatim matcher treats
   ``//`` ≠ ``/`` so the rule never matches. The fix collapses ``//`` → ``/``.
   Version-pinned plugin paths are deliberately NOT rewritten to ``**``
   wildcards (GH-715) — ``**`` matching is unreliable in the permission
   engine; pinned paths are kept current by
   ``dev10x permission update-paths`` on every upgrade instead.

2. **Cross-contamination** — rules referencing another project's
   absolute path (copy-paste leakage) and, in worktree CWDs, rules
   referencing the source repo by absolute path when a relative path
   inside the worktree would work.

3. **Catalog application** — load the baseline-permissions catalog
   (``baseline-permissions.yaml``, shipped alongside this module as
   package data) and apply deprecation actions (canonicalize / remove)
   plus invariant checks.

CLI entry points live under ``dev10x permission doctor``.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dev10x import subprocess_utils
from dev10x.domain.common.baseline_catalog import load_baseline_dict
from dev10x.domain.common.policy import Policy, PolicyAssessment, PolicyCatalog

CATALOG_PATH = Path(__file__).resolve().parent / "baseline-permissions.yaml"

# GH-704: ``${CLAUDE_PLUGIN_ROOT}`` resolves with a trailing slash, so the
# expanded command (and Claude Code's "don't ask again" remediation) bakes a
# literal ``//`` into ``settings`` (e.g. ``.../<ver>//skills/...``). The
# verbatim matcher treats ``//`` ≠ ``/`` so the polluted rule never matches.
# The ``(?<!:)`` guard leaves scheme separators like ``mcp://`` untouched.
_DUP_SLASH_RE = re.compile(r"(?<!:)/{2,}")


def canonicalize_rule(rule: str) -> str | None:
    """Normalize a single allow-rule string to canonical form.

    Returns the rewritten rule, or ``None`` when no rewrite applies.

    The only rewrite is collapsing duplicate slashes (``//`` → ``/``)
    outside a ``://`` scheme (GH-704) so ``${CLAUDE_PLUGIN_ROOT}``
    trailing-slash pollution matches the verbatim engine.

    Version-pinned plugin paths are deliberately NOT rewritten to ``**``
    wildcards (GH-715): ``**`` matching is unreliable in the permission
    engine, so pinned paths are kept current by
    ``dev10x permission update-paths`` on each upgrade instead.
    """
    collapsed = _DUP_SLASH_RE.sub("/", rule)
    if collapsed == rule:
        return None
    return collapsed


@dataclass
class CanonicalizeResult:
    rewrites: list[tuple[str, str]] = field(default_factory=list)
    unchanged: int = 0

    @property
    def changed(self) -> int:
        return len(self.rewrites)


def canonicalize_rules(rules: Iterable[str]) -> CanonicalizeResult:
    """Apply ``canonicalize_rule`` across an iterable, deduping the output."""
    result = CanonicalizeResult()
    seen: set[str] = set()
    for rule in rules:
        rewritten = canonicalize_rule(rule)
        target = rewritten if rewritten is not None else rule
        if rewritten is not None:
            result.rewrites.append((rule, rewritten))
        else:
            result.unchanged += 1
        seen.add(target)
    return result


def _canonicalize_in_place(data: dict[str, Any]) -> CanonicalizeResult:
    perms = data.get("permissions", {})
    result = CanonicalizeResult()
    for bucket in ("allow", "deny", "ask"):
        rules = perms.get(bucket)
        if not isinstance(rules, list):
            continue
        new_rules: list[str] = []
        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, str):
                new_rules.append(rule)
                continue
            rewritten = canonicalize_rule(rule)
            final = rewritten if rewritten is not None else rule
            if rewritten is not None:
                result.rewrites.append((rule, rewritten))
            else:
                result.unchanged += 1
            if final in seen:
                continue
            seen.add(final)
            new_rules.append(final)
        perms[bucket] = new_rules
    data["permissions"] = perms
    return result


def canonicalize_settings_file(
    settings_path: Path,
    *,
    dry_run: bool = False,
) -> CanonicalizeResult:
    """Rewrite pinned plugin paths in a settings.json file.

    Operates on ``permissions.allow`` and ``permissions.deny`` lists.
    Dedupes after rewriting — collisions with already-canonical rules
    collapse silently. The write goes through ``locked_json_update`` +
    ``create_backup`` so parallel agents cannot clobber each other's
    rules (GH-572).
    """
    result = _canonicalize_in_place(json.loads(settings_path.read_text()))
    if dry_run or not result.changed:
        return result

    from dev10x.skills.permission.backup import create_backup
    from dev10x.skills.permission.file_lock import locked_json_update

    create_backup(settings_path)
    with locked_json_update(path=settings_path) as live_data:
        return _canonicalize_in_place(live_data)


@dataclass
class CrossContaminationFinding:
    rule: str
    reason: str
    suggestion: str


@dataclass
class WorkspaceContext:
    project_root: Path
    git_common_dir: Path | None = None

    @property
    def is_worktree(self) -> bool:
        if self.git_common_dir is None:
            return False
        return self.git_common_dir.resolve().parent != self.project_root.resolve()

    @property
    def source_repo(self) -> Path | None:
        if not self.is_worktree or self.git_common_dir is None:
            return None
        return self.git_common_dir.resolve().parent


def detect_workspace(cwd: Path) -> WorkspaceContext:
    """Detect project root and (if worktree) source repo via git."""
    try:
        toplevel = subprocess_utils.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return WorkspaceContext(project_root=cwd)
    try:
        common_dir = subprocess_utils.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return WorkspaceContext(project_root=Path(toplevel))
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = (Path(toplevel) / common_path).resolve()
    return WorkspaceContext(
        project_root=Path(toplevel),
        git_common_dir=common_path,
    )


_ABSOLUTE_PATH_RE = re.compile(r"\((?:[A-Za-z]+:\s*)?(?P<path>/[^):*\s]+)")


SYSTEM_PATH_PREFIXES = ("/usr/", "/etc/", "/var/", "/opt/")


def _extract_absolute_path(rule: str) -> str | None:
    """Pull the first absolute filesystem path out of a rule string."""
    match = _ABSOLUTE_PATH_RE.search(rule)
    if match is None:
        return None
    return match["path"]


def _is_system_path(path_str: str) -> bool:
    """Heuristic: paths under /usr, /etc, /var, /opt are system tooling.

    ``/tmp`` is intentionally excluded — Dev10x uses ``/tmp/Dev10x/...``
    extensively and pytest fixtures live under ``/tmp/pytest-...``. The
    caller decides whether to skip /tmp paths after checking project
    membership.
    """
    return path_str.startswith(SYSTEM_PATH_PREFIXES)


def detect_cross_contamination(
    rules: Iterable[str],
    *,
    workspace: WorkspaceContext,
) -> list[CrossContaminationFinding]:
    """Flag rules whose absolute paths leak across projects or into the source repo."""
    findings: list[CrossContaminationFinding] = []
    project_resolved = workspace.project_root.resolve()
    source_resolved = workspace.source_repo.resolve() if workspace.source_repo else None
    for rule in rules:
        if not isinstance(rule, str):
            continue
        path_str = _extract_absolute_path(rule)
        if path_str is None:
            continue
        path = Path(path_str)
        if str(path).startswith(str(Path.home())):
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if _is_within(resolved, project_resolved):
            continue
        if _is_system_path(path_str) and not (
            source_resolved is not None and _is_within(resolved, source_resolved)
        ):
            continue
        if path_str.startswith("/tmp/") and not (
            source_resolved is not None and _is_within(resolved, source_resolved)
        ):
            continue
        if source_resolved is not None and _is_within(resolved, source_resolved):
            findings.append(
                CrossContaminationFinding(
                    rule=rule,
                    reason=(
                        "Path points into the source repository while CWD is "
                        "a worktree. The same files exist relative to the "
                        "worktree — use a relative path instead."
                    ),
                    suggestion=(
                        f"Rewrite to a relative path or remove the rule. Source: {source_resolved}"
                    ),
                )
            )
            continue
        findings.append(
            CrossContaminationFinding(
                rule=rule,
                reason=(
                    "Absolute path is outside this project root — likely "
                    "copy-pasted from another repo's settings."
                ),
                suggestion=(
                    f"Remove the rule or move it to the owning project. "
                    f"Project: {project_resolved}"
                ),
            )
        )
    return findings


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def cross_contamination_for_root(*, root: Path, quiet: bool = False) -> dict[str, Any]:
    """Read a project's settings file and report cross-contamination findings.

    Resolves the workspace for ``root``, reads
    ``<project>/.claude/settings.local.json``, collects allow/deny/ask
    rules, and runs :func:`detect_cross_contamination`. Returns a result
    dict consumable by ``commands.permission._emit_result``.
    """
    workspace = detect_workspace(root)
    settings_path = workspace.project_root / ".claude" / "settings.local.json"
    if not settings_path.is_file():
        return {"messages": [f"No settings file at {settings_path}"], "exit_code": 0}

    data = json.loads(settings_path.read_text())
    rules: list[str] = []
    perms = data.get("permissions", {})
    for bucket in ("allow", "deny", "ask"):
        rules.extend(perms.get(bucket, []) or [])

    findings = detect_cross_contamination(rules, workspace=workspace)
    if not findings:
        return {
            "messages": [f"{settings_path} — no cross-contamination findings."],
            "exit_code": 0,
        }

    messages = [f"\n{settings_path} — {len(findings)} findings"]
    for finding in findings:
        messages.append(f"  ! {finding.rule}")
        if not quiet:
            messages.append(f"      reason: {finding.reason}")
            messages.append(f"      suggestion: {finding.suggestion}")
    return {"messages": messages, "exit_code": 0}


def expand_flag_overrides(flag_overrides: dict[str, list[str]]) -> list[str]:
    """Expand a ``flag_overrides`` mapping into ``Bash(<cmd> <flag>:*)`` rules.

    For each base command ``B`` and safe flag ``F``, emit ``Bash(B F:*)``.
    Order is deterministic: mapping order, then flag-list order. Duplicate
    rules collapse while preserving first-seen order (GH-372).
    """
    rules: list[str] = []
    seen: set[str] = set()
    for command, flags in flag_overrides.items():
        for flag in flags:
            rule = f"Bash({command} {flag}:*)"
            if rule in seen:
                continue
            seen.add(rule)
            rules.append(rule)
    return rules


def _effective_group_rules(group: dict) -> list[str]:
    """Explicit ``rules`` first, then expanded ``flag_overrides``, de-duped."""
    output: list[str] = []
    seen: set[str] = set()
    for rule in group.get("rules", []):
        if rule in seen:
            continue
        seen.add(rule)
        output.append(rule)
    for rule in expand_flag_overrides(group.get("flag_overrides", {})):
        if rule in seen:
            continue
        seen.add(rule)
        output.append(rule)
    return output


@dataclass
class Catalog:
    version: int
    last_audited: str
    groups: dict[str, dict]
    deprecations: list[dict]
    invariants: list[dict]

    def tier_rules(self, *, tiers: Iterable[int]) -> list[str]:
        tier_set = set(tiers)
        rules: list[str] = []
        for group in self.groups.values():
            if group.get("tier") in tier_set:
                rules.extend(_effective_group_rules(group))
        return rules

    def group_rules(self, name: str) -> list[str]:
        return _effective_group_rules(self.groups.get(name, {}))

    def policies(self) -> list[Policy]:
        """The catalog as typed Policy entries (PAP-4, GH-801)."""
        return PolicyCatalog.from_baseline_dict({"groups": self.groups})


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    """Load the baseline-permissions catalog from YAML.

    Reading and parsing the baseline YAML is delegated to the shared
    loader (GH-587); ``strict=True`` preserves the raise-on-missing
    contract this consumer has always had.
    """
    raw = load_baseline_dict(path, strict=True)
    return Catalog(
        version=int(raw.get("version", 0)),
        last_audited=str(raw.get("last_audited", "")),
        groups=raw.get("groups", {}),
        deprecations=raw.get("deprecations", []),
        invariants=raw.get("invariants", []),
    )


@dataclass
class DeprecationOutcome:
    rule: str
    action: str
    replacement: str | None = None
    reason: str = ""

    def as_assessment(self) -> PolicyAssessment:
        """Record this outcome as a Policy assessment (PAP-4, GH-801)."""
        verdict = self.action if self.replacement is None else f"{self.action}:{self.replacement}"
        return PolicyAssessment(kind="doctor-deprecation", verdict=verdict, note=self.reason)


def apply_deprecations(
    rules: Iterable[str],
    *,
    catalog: Catalog,
) -> tuple[list[str], list[DeprecationOutcome]]:
    """Apply catalog deprecations to a list of rules.

    Returns the rewritten rule list (with removals dropped) and a list of
    outcomes describing what changed.
    """
    outcomes: list[DeprecationOutcome] = []
    output: list[str] = []
    seen: set[str] = set()
    compiled = [
        (re.compile(entry["pattern"]), entry)
        for entry in catalog.deprecations
        if entry.get("pattern")
    ]
    for rule in rules:
        if not isinstance(rule, str):
            output.append(rule)
            continue
        matched_entry = None
        for pattern, entry in compiled:
            if pattern.search(rule):
                matched_entry = entry
                break
        if matched_entry is None:
            if rule not in seen:
                output.append(rule)
                seen.add(rule)
            continue
        action = matched_entry.get("action", "remove")
        reason = matched_entry.get("reason", "")
        if action == "remove":
            outcomes.append(DeprecationOutcome(rule=rule, action="remove", reason=reason))
            continue
        if action == "canonicalize":
            replacement = canonicalize_rule(rule) or rule
            outcomes.append(
                DeprecationOutcome(
                    rule=rule,
                    action="canonicalize",
                    replacement=replacement,
                    reason=reason,
                )
            )
            if replacement not in seen:
                output.append(replacement)
                seen.add(replacement)
            continue
        # Unknown action — keep the rule, flag the outcome.
        outcomes.append(DeprecationOutcome(rule=rule, action=action, reason=reason))
        if rule not in seen:
            output.append(rule)
            seen.add(rule)
    return output, outcomes


def apply_deprecations_to_files(
    settings_files: Iterable[Path],
    *,
    catalog: Catalog,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply catalog deprecations across settings files, writing changes.

    Reads each file, applies :func:`apply_deprecations` per
    allow/deny/ask bucket, and (unless ``dry_run``) writes the result
    back. Returns a result dict consumable by
    ``commands.permission._emit_result``.
    """
    messages: list[str] = []
    total_actions = 0
    for path in sorted(settings_files):
        data = json.loads(path.read_text())
        perms = data.get("permissions", {})
        changes_in_file = 0
        for bucket in ("allow", "deny", "ask"):
            rules = perms.get(bucket)
            if not isinstance(rules, list):
                continue
            new_rules, outcomes = apply_deprecations(rules, catalog=catalog)
            if outcomes:
                changes_in_file += len(outcomes)
                messages.append(f"\n{path} [{bucket}] — {len(outcomes)} actions")
                for outcome in outcomes:
                    if outcome.action == "remove":
                        messages.append(f"  - REMOVE: {outcome.rule}  # {outcome.reason}")
                    elif outcome.action == "canonicalize":
                        messages.append(f"  ~ CANON:  {outcome.rule}")
                        messages.append(f"           → {outcome.replacement}")
                    else:
                        messages.append(f"  ? {outcome.action.upper()}: {outcome.rule}")
            perms[bucket] = new_rules
        if changes_in_file and not dry_run:
            from dev10x.skills.permission.backup import create_backup
            from dev10x.skills.permission.file_lock import locked_json_update

            create_backup(path)
            with locked_json_update(path=path) as live_data:
                live_perms = live_data.get("permissions", {})
                for bucket in ("allow", "deny", "ask"):
                    live_rules = live_perms.get(bucket)
                    if not isinstance(live_rules, list):
                        continue
                    live_perms[bucket], _ = apply_deprecations(live_rules, catalog=catalog)
                live_data["permissions"] = live_perms
        total_actions += changes_in_file
    verb = "Would apply" if dry_run else "Applied"
    messages.append(f"\n{verb} {total_actions} deprecation actions.")
    return {"messages": messages, "exit_code": 0}


def enable_group_in_files(
    settings_files: Iterable[Path],
    *,
    rules: Iterable[str],
    group_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add a catalog group's ``rules`` to each settings file's allow bucket.

    Rules already present are skipped. Unless ``dry_run``, the updated
    allow bucket is written back. Returns a result dict consumable by
    ``commands.permission._emit_result``.
    """
    rule_list = list(rules)
    messages: list[str] = []
    total_added = 0
    for path in sorted(settings_files):
        data = json.loads(path.read_text())
        perms = data.setdefault("permissions", {})
        allow = perms.setdefault("allow", [])
        added_here = [rule for rule in rule_list if rule not in allow]
        if not added_here:
            continue
        messages.append(f"\n{path} — adding {len(added_here)} rules from {group_name!r}")
        for rule in added_here:
            messages.append(f"  + {rule}")
        if not dry_run:
            from dev10x.skills.permission.backup import create_backup
            from dev10x.skills.permission.file_lock import locked_json_update

            create_backup(path)
            with locked_json_update(path=path) as live_data:
                live_perms = live_data.setdefault("permissions", {})
                live_allow = live_perms.setdefault("allow", [])
                live_allow.extend(rule for rule in rule_list if rule not in live_allow)
        total_added += len(added_here)
    verb = "Would add" if dry_run else "Added"
    messages.append(f"\n{verb} {total_added} rules from group {group_name!r}.")
    return {"messages": messages, "exit_code": 0}


@dataclass
class WorktreeAnchorFinding:
    worktrees_parent: Path
    settings_path: Path
    scope: str  # "workspace" | "skill-script"
    rule: str | None = None  # for skill-script findings
    suggestion: str = ""


@dataclass
class WorktreeAnchorResult:
    workspace_anchored: int = 0  # total additionalDirectories entries added
    findings: list[WorktreeAnchorFinding] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return self.workspace_anchored


_RELATIVE_SKILL_SCRIPT_RE = re.compile(r"Bash\(\.claude/skills/(?P<tail>[^:)]+)")


def discover_worktrees_parents(roots: Iterable[str]) -> list[Path]:
    """Return unique `.worktrees` parent paths found beneath each root.

    A `.worktrees` parent is a project directory that contains a
    `.worktrees/` subdirectory. Anchoring the parent covers all
    sibling and future worktrees without re-prompting per leaf.
    """
    parents: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
        # Depth-1 scan: check immediate children and root itself
        candidates = [root_path] + list(root_path.iterdir())
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            wt_dir = candidate / ".worktrees"
            if wt_dir.is_dir():
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    parents.append(candidate)
    return parents


def anchor_worktree_roots(
    settings_files: Iterable[Path],
    *,
    roots: Iterable[str],
    dry_run: bool = False,
) -> WorktreeAnchorResult:
    """Anchor `.worktrees` parent roots across workspace and skill-script scopes.

    For each settings file:

    1. **Workspace scope** — ensure every discovered `<project>/.worktrees`
       parent is present in ``permissions.additionalDirectories``. Anchoring
       the parent covers all sibling and future worktrees without re-prompting
       per leaf (GH-376).

    2. **Skill-script scope** — detect bare-relative allow rules of the form
       ``Bash(.claude/skills/<name>/scripts/<name>.py:*)`` and flag them for
       rewriting to the absolute, CWD-independent plugin-cache path (or
       ``Skill(<name>)`` invocation). Relative rules silently point at
       different skill dirs per worktree and must be absolute to be stable.

    Returns a :class:`WorktreeAnchorResult` summarising changes made (or that
    would be made on ``dry_run=True``).
    """
    from dev10x.skills.permission.update_paths import ensure_workspace_directories

    worktrees_parents = discover_worktrees_parents(roots)
    parent_strs = [str(p) for p in worktrees_parents]

    result = WorktreeAnchorResult()

    for settings_path in settings_files:
        if not settings_path.exists():
            continue

        # 1. Workspace anchoring
        if parent_strs:
            count, _ = ensure_workspace_directories(
                settings_path,
                parent_strs,
                dry_run=dry_run,
            )
            if count > 0:
                result.workspace_anchored += count
                result.findings.append(
                    WorktreeAnchorFinding(
                        worktrees_parent=worktrees_parents[0]
                        if worktrees_parents
                        else settings_path.parent,
                        settings_path=settings_path,
                        scope="workspace",
                        suggestion=(
                            f"Anchored {count} worktrees parent(s) in "
                            f"additionalDirectories: {settings_path}"
                        ),
                    )
                )

        # 2. Skill-script rule detection
        try:
            import json as _json

            data = _json.loads(settings_path.read_text())
        except (OSError, ValueError):
            continue
        allow_rules: list[str] = data.get("permissions", {}).get("allow", [])
        for rule in allow_rules:
            if not isinstance(rule, str):
                continue
            if _RELATIVE_SKILL_SCRIPT_RE.search(rule):
                suggestion = (
                    "Rewrite to absolute plugin-cache path or replace "
                    "with Skill() invocation. Relative paths resolve against "
                    "CWD and silently target different skill dirs per worktree."
                )
                result.findings.append(
                    WorktreeAnchorFinding(
                        worktrees_parent=settings_path.parent,
                        settings_path=settings_path,
                        scope="skill-script",
                        rule=rule,
                        suggestion=suggestion,
                    )
                )

    return result


def diagnose_additional_directories(
    rule: str,
    *,
    path_arguments: Iterable[str],
    additional_directories: Iterable[str],
) -> str | None:
    """Return a diagnostic message when a Bash rule is fine but the path is out of scope.

    A persistent prompt despite a matching Bash allow rule almost always
    indicates the command's path arguments fall outside the registered
    ``additionalDirectories``. This returns the directory the user should
    add, or ``None`` when no diagnosis applies.

    The caller is expected to know which Bash rule fired (``rule``), what
    path arguments the command carried (``path_arguments``), and which
    directories are currently registered (``additional_directories``).
    """
    additional = [Path(d).expanduser().resolve() for d in additional_directories]
    for arg in path_arguments:
        try:
            resolved = Path(arg).expanduser().resolve()
        except OSError:
            continue
        if any(_is_within(resolved, parent) for parent in additional):
            continue
        if resolved.exists() or resolved.parent.exists():
            return (
                f"Bash rule {rule!r} matched, but path {arg!r} is outside "
                f"registered additionalDirectories. Add "
                f"{resolved.parent if resolved.is_file() else resolved} to "
                f"additionalDirectories in .claude/settings.local.json — "
                f"this is a path-scope issue, not a Bash allow-rule issue."
            )
    return None
