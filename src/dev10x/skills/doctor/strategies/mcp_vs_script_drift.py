"""Strategy: mcp-vs-script-drift (GH-87).

Detects memory files, settings allow rules, and SKILL.md examples
that reference shell-script paths when an MCP tool offers the
same capability. The intent is to surface — not silently fix —
the channels through which obsolete script names leak back into
the agent's context.

See ``skills/doctor/references/mcp-vs-script-drift.md`` for the
full equivalence table and detection heuristics.
"""

from __future__ import annotations

from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)

SCRIPT_TO_MCP: dict[str, str] = {
    "/tmp/Dev10x/bin/mktmp.sh": "mcp__plugin_Dev10x_cli__mktmp",
    "skills/gh-context/scripts/gh-issue-get.sh": "mcp__plugin_Dev10x_cli__issue_get",
    "skills/gh-context/scripts/gh-issue-comments.sh": "mcp__plugin_Dev10x_cli__issue_comments",
    "skills/gh-context/scripts/gh-issue-create.sh": "mcp__plugin_Dev10x_cli__issue_create",
    "skills/gh-context/scripts/gh-pr-detect.sh": "mcp__plugin_Dev10x_cli__pr_detect",
    "skills/gh-pr-monitor/scripts/ci-check-status.py": "mcp__plugin_Dev10x_cli__ci_check_status",
    "skills/git/scripts/git-push-safe.sh": "mcp__plugin_Dev10x_cli__push_safe",
    "skills/gh-pr-create/scripts/create-pr.sh": "mcp__plugin_Dev10x_cli__create_pr",
}


def _scan_memory(*, context: Context) -> list[Finding]:
    findings: list[Finding] = []
    for memory_root in context.memory_roots:
        if not memory_root.exists():
            continue
        for path in memory_root.rglob("*.md"):
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for script_token, mcp_tool in SCRIPT_TO_MCP.items():
                if script_token in text:
                    findings.append(
                        Finding(
                            strategy_id="mcp-vs-script-drift",
                            severity="drift",
                            location=str(path),
                            evidence=f"memory references obsolete script ({script_token!r})",
                            proposed_fix=(
                                f"rewrite memory body to reference the MCP tool "
                                f"({mcp_tool}) instead — avoid quoting the obsolete "
                                f"path even in negative examples"
                            ),
                            metadata={
                                "mcp_tool": mcp_tool,
                                "script_marker": script_token,
                            },
                        )
                    )
    return findings


def _scan_skill_docs(*, context: Context) -> list[Finding]:
    findings: list[Finding] = []
    plugin_root = context.plugin_cache_root
    if plugin_root is None or not plugin_root.exists():
        return findings

    for skill_md in plugin_root.rglob("SKILL.md"):
        try:
            text = skill_md.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for script_token, mcp_tool in SCRIPT_TO_MCP.items():
            if script_token not in text:
                continue
            if mcp_tool in text and text.find(script_token) < text.find(mcp_tool):
                findings.append(
                    Finding(
                        strategy_id="mcp-vs-script-drift",
                        severity="suggestion",
                        location=str(skill_md),
                        evidence=(
                            f"SKILL.md shows script form before MCP form "
                            f"(script appears before {mcp_tool})"
                        ),
                        proposed_fix=(
                            "reorder examples so the MCP tool is the only "
                            "first-class option; demote the script form to a "
                            "footnoted fallback"
                        ),
                        metadata={
                            "mcp_tool": mcp_tool,
                            "script_marker": script_token,
                        },
                    )
                )
    return findings


def detect(context: Context) -> list[Finding]:
    return [*_scan_memory(context=context), *_scan_skill_docs(context=context)]


def remediate(finding: Finding) -> Remediation:
    if "memory" in finding.evidence:
        return Remediation(
            kind="edit_memory",
            target=finding.location,
            action={"mcp_tool": finding.metadata.get("mcp_tool")},
        )
    return Remediation(
        kind="file_issue",
        target=finding.location,
        action={"mcp_tool": finding.metadata.get("mcp_tool")},
    )


STRATEGY = Strategy(
    id="mcp-vs-script-drift",
    description=(
        "Surface memory/settings/SKILL.md drift toward obsolete script "
        "paths when an MCP equivalent exists."
    ),
    detect=detect,
    remediate=remediate,
)
