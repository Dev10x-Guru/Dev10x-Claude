"""Dry-run promotion plan for read-only MCP tools and research WebFetch
domains (GH-470, Increment 1).

MCP approvals are scoped per tool-name x per project-directory, so a
read-only tool used across many projects re-prompts in each one. This
module classifies discovered MCP tools as read-only vs write using a
name-token heuristic and builds a DRY-RUN plan describing which tools
and research-fetch domains WOULD be promoted to global settings.

**No writes.** This module never mutates settings — it only reports a
plan a human reviews. Actual promotion to global settings is deferred to
a follow-up (Increment 2). The heuristic carries false-positive risk —
e.g. a grant named ``get_access_to_*`` reads as ``read`` by token — so a
reviewable dry-run is the safety floor before any auto-write lands.

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
    }
)
# Read tools whose target is private/DM/secret — promotable only on opt-in.
SENSITIVE_TOKENS = frozenset(
    {"private", "secret", "secrets", "credential", "credentials", "password", "dm"}
)

_WEBFETCH_RE = re.compile(r"^WebFetch\(domain:(?P<domain>.+)\)$")


def _short_name(full_tool_name: str) -> str:
    """Return the tool name after the final ``__`` separator, lowercased."""
    return full_tool_name.rsplit("__", 1)[-1].lower()


def _tokens(full_tool_name: str) -> set[str]:
    return set(_short_name(full_tool_name).split("_"))


def classify_mcp_tool(full_tool_name: str) -> str:
    """Classify a fully-qualified MCP tool name as read/write/unknown.

    Write-precedence: any write token wins, so a write is never
    misclassified as promotable.
    """
    tokens = _tokens(full_tool_name)
    if tokens & WRITE_TOKENS:
        return "write"
    if tokens & READ_TOKENS:
        return "read"
    return "unknown"


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
            if not rule.startswith("mcp__") or rule.endswith("*"):
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
        "Increment 1 is read-only: this plan performs NO writes. "
        "Review it, then apply via the follow-up promotion step (Increment 2)."
    )
    return "\n".join(lines)
