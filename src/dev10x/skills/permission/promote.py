"""Dry-run promotion plan for read-only MCP tools and research WebFetch
domains (GH-470, Increment 1).

MCP approvals are scoped per tool-name x per project-directory, so a
read-only tool used across many projects re-prompts in each one. This
module classifies discovered MCP tools as read-only vs write using a
name-token heuristic and builds a DRY-RUN plan describing which tools
and research-fetch domains WOULD be promoted to global settings.

**Two-phase by design.** ``build_promotion_plan`` only *reports* a plan a
human reviews — it never mutates settings. ``apply_promotion_plan``
(Increment 2, GH-480) writes the approved read-only set + research domains
into global settings, backup-guarded and idempotent, behind an explicit
opt-in (the ``--apply`` flag). The heuristic carries false-positive risk —
e.g. a grant named ``get_access_to_*`` would read as ``read`` by its ``get``
token, so ``access``/``grant``/``authorize`` are write tokens
(write-precedence) — and the dry-run plan remains the safety floor a human
reviews before any auto-write lands.

Classification (write-precedence — safer to under-promote):

- A tool is ``write`` if its short name contains ANY write token.
- Else ``read`` if it contains any read token.
- Else ``unknown``.

Only read tools are promotable. Sensitivity-flagged read tools (private
/ DM / secret access) are reported separately as opt-in — never folded
into the default promotable set. Plugin-distributed tools are skipped:
they are promoted through ``enumerate-mcp`` + base_permissions, not here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.domain.common.mcp_tool_name import McpToolName
from dev10x.skills.permission.enumerate_mcp import (
    _server_prefix_from_tool,
    _source_type_from_prefix,
)

# Verb tokens (matched against the short tool name split on `_`).
READ_TOKENS = frozenset(
    {
        "read",
        "search",
        "list",
        "get",
        "find",
        "fetch",
        "query",
        "lookup",
        "show",
        "check",
        "describe",
        "view",
        "count",
        "whoami",
    }
)
WRITE_TOKENS = frozenset(
    {
        "create",
        "update",
        "delete",
        "remove",
        "send",
        "schedule",
        "add",
        "edit",
        "save",
        "set",
        "post",
        "merge",
        "close",
        "reopen",
        "deploy",
        "respond",
        "reply",
        "transition",
        "move",
        "copy",
        "archive",
        "label",
        "unlabel",
        "submit",
        "complete",
        "authenticate",
        "manage",
        "change",
        "download",
        "upload",
        "prepare",
        "run",
        "execute",
        "build",
        "rename",
        "open",
        "write",
        "minimize",
        "request",
        "start",
        "push",
        "notify",
        # Grant/authorization verbs are side-effecting. A ``get_access_to_*``
        # tool reads as ``read`` by its ``get`` token but actually mints an
        # access grant — write-precedence keeps it out of the auto-promotable
        # set (GH-480: classifier corpus false-positive, e.g.
        # ``get_access_to_vercel_url``).
        "access",
        "grant",
        "authorize",
    }
)
# Read tools whose target is private/DM/secret — promotable only on opt-in.
SENSITIVE_TOKENS = frozenset(
    {"private", "secret", "secrets", "credential", "credentials", "password", "dm"}
)

_WEBFETCH_RE = re.compile(r"^WebFetch\(domain:(?P<domain>.+)\)$")

# Token boundaries: an acronym run before a CamelWord (``HTTPSConnection`` →
# ``HTTPS`` + ``Connection``), a Capitalized-or-lowercase word, a bare acronym,
# or a digit run. Splitting on this AND ``_`` lets camelCase MCP tools
# (``getJiraIssue``, ``createJiraIssue``) tokenize by verb instead of
# collapsing into one unsplittable ``unknown`` token (GH-593).
_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def _short_name(full_tool_name: str) -> str:
    """Return the tool name after the final ``__`` separator (original case).

    Case is preserved so :func:`_tokens` can detect camelCase boundaries;
    callers that need a verb set get lowercased tokens from ``_tokens``.
    """
    return full_tool_name.rsplit("__", 1)[-1]


def _tokens(full_tool_name: str) -> set[str]:
    """Split a tool's short name into lowercase verb tokens.

    Splits on both ``_`` and camelCase boundaries (GH-593) so a camelCase
    server such as ``getJiraIssue`` yields ``{get, jira, issue}`` — and its
    ``get``/``create`` verb drives classification — rather than collapsing
    to a single ``unknown`` token.
    """
    return {
        match.group(0).lower()
        for chunk in _short_name(full_tool_name).split("_")
        for match in _TOKEN_RE.finditer(chunk)
    }


def classify_tokens(name: str) -> str:
    """Classify any verb-bearing name (CLI command, skill, tool) as read/write/unknown.

    Splits *name* into tokens (camelCase + snake_case + digits, GH-593) and
    applies write-precedence: any write token wins, so a write is never
    misclassified as promotable. Used by both :func:`classify_mcp_tool` and the
    source-derived manifest generators (GH-600), so every surface — MCP, CLI,
    skill — shares one classifier.
    """
    tokens = _tokens(name)
    if tokens & WRITE_TOKENS:
        return "write"
    if tokens & READ_TOKENS:
        return "read"
    return "unknown"


def classify_mcp_tool(full_tool_name: str) -> str:
    """Classify a fully-qualified MCP tool name as read/write/unknown.

    Write-precedence: any write token wins, so a write is never
    misclassified as promotable.
    """
    return classify_tokens(full_tool_name)


def is_sensitivity_flagged(full_tool_name: str) -> bool:
    """Return True when the tool reads private/DM/secret data (opt-in only)."""
    return bool(_tokens(full_tool_name) & SENSITIVE_TOKENS)


def _read_allow_rules(path: Path) -> list[str]:
    """Return the ``permissions.allow`` list, or [] if missing/unreadable."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    allow = data.get("permissions", {}).get("allow", [])
    return [r for r in allow if isinstance(r, str)]


def collect_webfetch_domains(path: Path) -> set[str]:
    """Return the set of ``WebFetch(domain:X)`` domains in an allow list."""
    domains: set[str] = set()
    for rule in _read_allow_rules(path):
        match = _WEBFETCH_RE.match(rule)
        if match:
            domains.add(match.group("domain"))
    return domains


@dataclass
class PromotionPlan:
    """Dry-run description of what WOULD be promoted to global settings.

    Every field is advisory — the caller renders and reviews it. No
    promotion is executed by building this plan.
    """

    read_promotable: list[str] = field(default_factory=list)
    sensitive_opt_in: list[str] = field(default_factory=list)
    writes_excluded: list[str] = field(default_factory=list)
    unknown_excluded: list[str] = field(default_factory=list)
    domains_promotable: list[str] = field(default_factory=list)
    already_global_tools: int = 0
    already_global_domains: int = 0

    @property
    def has_promotable(self) -> bool:
        return bool(self.read_promotable or self.domains_promotable)


def build_promotion_plan(
    *,
    project_settings_paths: Iterable[Path],
    global_settings_path: Path,
) -> PromotionPlan:
    """Build a dry-run promotion plan from project-local settings.

    Reads project-local allow rules, classifies each concrete (non-
    wildcard) MCP tool, and dedups against the global allow list. Only
    claude.ai-hosted and user-installed servers are considered — plugin-
    distributed tools are promoted through ``enumerate-mcp`` instead.
    """
    global_allow = set(_read_allow_rules(global_settings_path))
    global_domains = collect_webfetch_domains(global_settings_path)

    plan = PromotionPlan()
    seen: set[str] = set()

    for path in project_settings_paths:
        for rule in _read_allow_rules(path):
            if not McpToolName.is_mcp(rule) or rule.endswith("*"):
                continue
            if rule in seen:
                continue
            seen.add(rule)

            prefix = _server_prefix_from_tool(rule)
            if prefix is None:
                continue
            source_type, _ = _source_type_from_prefix(prefix)
            if source_type == "plugin":
                continue
            if rule in global_allow:
                plan.already_global_tools += 1
                continue

            kind = classify_mcp_tool(rule)
            if kind == "write":
                plan.writes_excluded.append(rule)
            elif kind == "unknown":
                plan.unknown_excluded.append(rule)
            elif is_sensitivity_flagged(rule):
                plan.sensitive_opt_in.append(rule)
            else:
                plan.read_promotable.append(rule)

    project_domains: set[str] = set()
    for path in project_settings_paths:
        project_domains |= collect_webfetch_domains(path)
    plan.already_global_domains = len(project_domains & global_domains)
    plan.domains_promotable = sorted(project_domains - global_domains)

    plan.read_promotable.sort()
    plan.sensitive_opt_in.sort()
    plan.writes_excluded.sort()
    plan.unknown_excluded.sort()
    return plan


def render_promotion_plan(plan: PromotionPlan) -> str:
    """Render a human-readable dry-run report of the promotion plan."""
    lines = ["MCP / research-domain promotion plan (DRY RUN — no files modified):", ""]

    def _section(title: str, items: list[str], marker: str) -> None:
        lines.append(f"{title} ({len(items)}):")
        for item in items:
            lines.append(f"  {marker} {item}")
        if not items:
            lines.append("  (none)")
        lines.append("")

    _section("Read-only tools — would promote to global allow", plan.read_promotable, "+")
    _section("Research WebFetch domains — would promote to global", plan.domains_promotable, "+")
    _section("Sensitive read tools — promote only on explicit opt-in", plan.sensitive_opt_in, "?")
    _section("Writes — never auto-promoted", plan.writes_excluded, "-")
    _section("Unclassified — excluded (review manually)", plan.unknown_excluded, "-")

    lines.append(
        f"Already global: {plan.already_global_tools} tool(s), "
        f"{plan.already_global_domains} domain(s) — skipped (idempotent)."
    )
    lines.append(
        "This is the dry-run plan (NO writes). Apply it with "
        "`dev10x permission promote-plan --apply` (Increment 2, GH-480)."
    )
    return "\n".join(lines)


@dataclass
class PromotionResult:
    """Outcome of applying a :class:`PromotionPlan` to global settings.

    ``added_*`` list the rules newly written; ``already_present`` counts
    plan rules that were already in the global allow list (the idempotent
    skip path). ``backup_path`` is the timestamped backup created before
    the write, or ``None`` when nothing was written (dry-run or no-op).
    """

    added_tools: list[str] = field(default_factory=list)
    added_sensitive: list[str] = field(default_factory=list)
    added_domains: list[str] = field(default_factory=list)
    already_present: int = 0
    backup_path: Path | None = None

    @property
    def total_added(self) -> int:
        return len(self.added_tools) + len(self.added_sensitive) + len(self.added_domains)


def apply_promotion_plan(
    *,
    plan: PromotionPlan,
    global_settings_path: Path,
    include_sensitive: bool = False,
    dry_run: bool = False,
) -> PromotionResult:
    """Write a plan's read-only tools + research domains into global settings.

    Backup-guarded and idempotent: a timestamped backup is created before any
    write, and rules already present in the live global allow list are counted
    (``already_present``) rather than re-appended. Writes are never promoted —
    the plan's ``read_promotable`` already excludes them via write-precedence.
    Sensitivity-flagged reads (``plan.sensitive_opt_in``) are written ONLY when
    ``include_sensitive`` is True — an explicit opt-in, never the default.

    The append is re-checked against the *live* allow list under an exclusive
    lock, so a concurrent writer cannot cause a duplicate rule.
    """
    domain_rules = [f"WebFetch(domain:{domain})" for domain in plan.domains_promotable]
    sensitive_rules = list(plan.sensitive_opt_in) if include_sensitive else []
    candidates: list[tuple[str, str]] = (
        [("tool", rule) for rule in plan.read_promotable]
        + [("sensitive", rule) for rule in sensitive_rules]
        + [("domain", rule) for rule in domain_rules]
    )

    existing = set(_read_allow_rules(global_settings_path))
    result = PromotionResult()
    pending: list[str] = []
    for kind, rule in candidates:
        if rule in existing:
            result.already_present += 1
            continue
        pending.append(rule)
        if kind == "tool":
            result.added_tools.append(rule)
        elif kind == "sensitive":
            result.added_sensitive.append(rule)
        else:
            result.added_domains.append(rule)

    if dry_run or not pending:
        return result

    from dev10x.skills.permission.backup import create_backup
    from dev10x.skills.permission.file_lock import locked_json_update

    result.backup_path = create_backup(global_settings_path)
    with locked_json_update(path=global_settings_path) as live:
        permissions = live.setdefault("permissions", {})
        allow = permissions.setdefault("allow", [])
        live_present = {rule for rule in allow if isinstance(rule, str)}
        # Re-check every candidate against the LIVE allow list (not the
        # pre-lock read) so a concurrent writer or a stale plan cannot
        # introduce a duplicate rule.
        for _kind, rule in candidates:
            if rule not in live_present:
                allow.append(rule)
                live_present.add(rule)
        permissions["allow"] = allow
    return result


def render_promotion_result(result: PromotionResult, *, dry_run: bool = False) -> str:
    """Render a human-readable report of an :func:`apply_promotion_plan` run."""
    header = "DRY RUN — no files modified" if dry_run else "applied to global settings"
    verb = "Would promote" if dry_run else "Promoted"
    lines = [f"MCP / research-domain promotion ({header}):", ""]

    def _section(title: str, items: list[str]) -> None:
        lines.append(f"{verb} {title} ({len(items)}):")
        for item in items:
            lines.append(f"  + {item}")
        if not items:
            lines.append("  (none)")
        lines.append("")

    _section("read-only tools", result.added_tools)
    _section("research WebFetch domains", result.added_domains)
    _section("sensitive read tools (opt-in)", result.added_sensitive)

    lines.append(
        f"Already present in global: {result.already_present} rule(s) — skipped (idempotent)."
    )
    if result.backup_path is not None:
        lines.append(f"Backup: {result.backup_path}")
    elif not dry_run and result.total_added == 0:
        lines.append("No changes — global settings already contained every promotable rule.")
    return "\n".join(lines)
