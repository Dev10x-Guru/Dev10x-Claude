"""Strategy: missing-linear-mcp-allow (GH-204).

Detects projects whose `settings.local.json` already approves at
least one Linear MCP tool — a strong signal that the project uses
Linear as its issue tracker — but is missing the baseline Linear
MCP allow rules shipped by `Dev10x:plugin-maintenance` /
`Dev10x:upgrade-cleanup`.

When Linear is in use, the baseline pre-approves the read+write
subset (Group A + B in `skills/upgrade-cleanup/projects.yaml`) so
each project does not have to re-approve the same tools. A finding
fires when a project shows Linear usage but is missing 5+ baseline
rules — that threshold avoids noise on projects that touch Linear
only incidentally.
"""

from __future__ import annotations

import json
from pathlib import Path

from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)

LINEAR_RULE_PREFIXES: tuple[str, ...] = (
    "mcp__claude_ai_Linear__",
    "mcp__linear-server__",
)

EXPECTED_BASELINE_TOOLS: tuple[str, ...] = (
    "mcp__claude_ai_Linear__get_issue",
    "mcp__claude_ai_Linear__list_issues",
    "mcp__claude_ai_Linear__save_comment",
    "mcp__claude_ai_Linear__save_issue",
    "mcp__claude_ai_Linear__list_projects",
)

MISSING_THRESHOLD = 3


def _has_linear_usage(rules: list[str]) -> bool:
    return any(
        any(rule.startswith(prefix) for prefix in LINEAR_RULE_PREFIXES)
        for rule in rules
    )


def _missing_baseline(rules: list[str]) -> list[str]:
    existing = set(rules)
    return [tool for tool in EXPECTED_BASELINE_TOOLS if tool not in existing]


def _read_allow_rules(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    perms = data.get("permissions", {})
    return list(perms.get("allow", []))


def detect(context: Context) -> list[Finding]:
    findings: list[Finding] = []
    for path in context.settings_paths:
        if not path.exists():
            continue
        rules = _read_allow_rules(path)
        if not _has_linear_usage(rules):
            continue
        missing = _missing_baseline(rules)
        if len(missing) < MISSING_THRESHOLD:
            continue
        findings.append(
            Finding(
                strategy_id="missing-linear-mcp-allow",
                severity="drift",
                location=str(path),
                evidence=(
                    f"project approves Linear MCP tools but is missing "
                    f"{len(missing)} of {len(EXPECTED_BASELINE_TOOLS)} baseline "
                    f"rules ({', '.join(missing[:3])}...)"
                ),
                proposed_fix=(
                    "run `Dev10x:upgrade-cleanup` (or `dev10x permission "
                    "ensure-base`) to install the Linear MCP baseline shipped "
                    "in `skills/upgrade-cleanup/projects.yaml`"
                ),
                metadata={
                    "missing_tools": missing,
                },
            )
        )
    return findings


def remediate(finding: Finding) -> Remediation:
    return Remediation(
        kind="delegate_skill",
        target="Dev10x:upgrade-cleanup",
        action={
            "reason": "install Linear MCP baseline allow rules",
            "missing_tools": finding.metadata.get("missing_tools", []),
        },
    )


STRATEGY = Strategy(
    id="missing-linear-mcp-allow",
    description=(
        "Surface projects that approve Linear MCP tools ad-hoc but are missing "
        "the baseline read+write subset shipped by Dev10x:upgrade-cleanup."
    ),
    detect=detect,
    remediate=remediate,
)
