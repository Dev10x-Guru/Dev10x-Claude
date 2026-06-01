"""Strategy: mcp-horizontal-duplicates (GH-371).

Detects when the same logical capability is provided by multiple MCP
server installations under different prefixes. The three source types
are:

  mcp__claude_ai_<Service>__*      # claude.ai-hosted
  mcp__<service>__*                # user-installed (claude mcp add)
  mcp__plugin_<plugin>_<srv>__*   # plugin-distributed

When N servers each expose the same short tool name (e.g.
``search_issues``), the catalog rules that target one prefix do not
cover the other N-1. This strategy surfaces the duplication so the
user can decide whether to consolidate or keep all sources.

Evidence basis: GH-271 #222 — three distinct Sentry MCP servers on
one machine (claude.ai, user-installed, plugin-distributed).
"""

from __future__ import annotations

from pathlib import Path

from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)
from dev10x.skills.permission.enumerate_mcp import (
    McpServerEntry,
    build_capability_groups,
    discover_all_mcp_servers,
)


def _settings_paths_from_context(context: Context) -> list[Path]:
    """Collect all settings paths the strategy should scan."""
    paths = list(context.settings_paths)
    if not paths:
        home = Path.home()
        paths = [
            home / ".claude" / "settings.json",
            home / ".claude" / "settings.local.json",
        ]
    return paths


def detect(context: Context) -> list[Finding]:
    """Scan allow rules for MCP tools that appear under multiple prefixes."""
    settings_paths = _settings_paths_from_context(context)
    servers: list[McpServerEntry] = discover_all_mcp_servers(
        settings_paths=settings_paths,
    )
    groups = build_capability_groups(servers)

    findings: list[Finding] = []
    for group in groups:
        if not group.is_duplicate():
            continue
        prefix_list = ", ".join(f"``{prefix}``" for prefix, _ in group.entries)
        findings.append(
            Finding(
                strategy_id="mcp-horizontal-duplicates",
                severity="suggestion",
                location="permissions.allow",
                evidence=(
                    f"capability ``{group.tool_name}`` is offered by "
                    f"{group.server_count} servers: {prefix_list}"
                ),
                proposed_fix=(
                    "Review feature parity across servers and consider whether "
                    "all sources are needed. Catalog rules for one prefix do not "
                    "cover the others — each needs its own allow entry. "
                    "Consolidating to a single source reduces auth/connection "
                    "overhead and simplifies the catalog."
                ),
                metadata={
                    "capability_group": group.capability_group,
                    "tool_name": group.tool_name,
                    "server_count": group.server_count,
                    "entries": [
                        {"prefix": prefix, "tool": tool} for prefix, tool in group.entries
                    ],
                },
            )
        )
    return findings


def remediate(finding: Finding) -> Remediation:
    """Propose surfacing the duplication as an informational file issue."""
    return Remediation(
        kind="file_issue",
        target="permissions.allow",
        action={
            "capability_group": finding.metadata.get("capability_group"),
            "server_count": finding.metadata.get("server_count"),
            "entries": finding.metadata.get("entries", []),
            "reason": (
                "Multiple MCP servers expose the same capability. "
                "Review and consolidate to reduce auth overhead."
            ),
        },
    )


STRATEGY = Strategy(
    id="mcp-horizontal-duplicates",
    description=(
        "Surface capabilities offered by multiple MCP server sources "
        "(claude.ai-hosted, user-installed, plugin-distributed) under "
        "different prefixes. Catalog rules for one prefix do not cover "
        "the others — the duplication may be intentional or accidental."
    ),
    detect=detect,
    remediate=remediate,
)
