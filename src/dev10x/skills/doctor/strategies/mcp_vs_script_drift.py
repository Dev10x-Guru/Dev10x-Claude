"""Strategy: mcp-vs-script-drift (GH-87).

Detects memory files, settings allow rules, and SKILL.md examples
that reference shell-script paths when an MCP tool offers the
same capability. The intent is to surface — not silently fix —
the channels through which obsolete script names leak back into
the agent's context.

See ``skills/plugin-doctor/references/mcp-vs-script-drift.md`` for the
full equivalence table and detection heuristics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    RemediationKind,
    Strategy,
)

_VERSION_SEGMENT = re.compile(r"^v?\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?$")


def _skill_body(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + len("\n---\n") :]


def _normalized_skill_path(skill_md: str, plugin_root: str) -> str:
    # The cache holds one tree per installed version, so the version is
    # the only axis safe to collapse. Segments before it identify the
    # plugin: dropping those would key two plugins that ship a
    # same-named skill to one entry and discard the second's finding.
    parts = list(Path(skill_md).relative_to(Path(plugin_root)).parts)
    if "skills" not in parts:
        return "/".join(parts)
    marker = parts.index("skills")
    if marker and _VERSION_SEGMENT.match(parts[marker - 1]):
        del parts[marker - 1]
    return "/".join(parts)


@dataclass(frozen=True)
class ScriptDriftRemediation:
    """Remediation payload for an mcp-vs-script-drift finding.

    ``kind`` is fixed at detection time (``edit_memory`` for memory
    files, ``file_issue`` for SKILL.md ordering), so the remediator
    no longer sniffs the evidence string to decide.
    """

    mcp_tool: str
    kind: RemediationKind

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind=self.kind,
            target=finding.location,
            action={"mcp_tool": self.mcp_tool},
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
                            data=ScriptDriftRemediation(
                                mcp_tool=mcp_tool,
                                kind="edit_memory",
                            ),
                        )
                    )
    return findings


def _scan_skill_docs(*, context: Context) -> list[Finding]:
    findings: list[Finding] = []
    plugin_root = context.plugin_cache_root
    if plugin_root is None or not plugin_root.exists():
        return findings

    seen: set[tuple[str, str, str]] = set()

    for skill_md in plugin_root.rglob("SKILL.md"):
        try:
            text = skill_md.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        body = _skill_body(text)
        for script_token, mcp_tool in SCRIPT_TO_MCP.items():
            if script_token not in body:
                continue
            if mcp_tool in body and body.find(script_token) < body.find(mcp_tool):
                dedupe_key = (
                    _normalized_skill_path(
                        skill_md=str(skill_md),
                        plugin_root=str(plugin_root),
                    ),
                    script_token,
                    mcp_tool,
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
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
                        data=ScriptDriftRemediation(
                            mcp_tool=mcp_tool,
                            kind="file_issue",
                        ),
                    )
                )
    return findings


def detect(context: Context) -> list[Finding]:
    return [*_scan_memory(context=context), *_scan_skill_docs(context=context)]


def remediate(finding: Finding) -> Remediation:
    return finding.to_remediation()


STRATEGY = Strategy(
    id="mcp-vs-script-drift",
    description=(
        "Surface memory/settings/SKILL.md drift toward obsolete script "
        "paths when an MCP equivalent exists."
    ),
    detect=detect,
    remediate=remediate,
)
