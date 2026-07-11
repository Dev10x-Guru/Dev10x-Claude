"""In-process audit report factory (GH-142).

Replaces the out-of-process invocation of
`skills/skill-audit/scripts/analyze-permissions.py` with an
importable Python factory. The standalone script remains as a CLI
shim so the skill-audit pipeline can still run analyze-permissions
from a Bash entry point.

The implementation reuses the parsers, classifiers, and writers
defined in `dev10x.audit.permissions_model` — keeping the analysis
logic inside the audit context (GH-244, I1 / ADR-0008) instead of
importing up into the skills layer. This factory is the seam that lets
MCP callers skip the subprocess hop and consume the report as data.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field, replace
from pathlib import Path

from dev10x.audit.permissions_model import (
    Finding,
    HygieneFinding,
    audit_script_hygiene,
    count_nuisance_patterns,
    detect_hook_denials,
    detect_known_friction,
    parse_additional_directories,
    parse_allow_rules,
    parse_tool_calls,
    propose_allow_rules,
    write_output,
)
from dev10x.audit.permissions_model import (
    analyze_permissions as _analyze_permissions,
)
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.subprocess_utils import effective_cwd


@dataclass
class AuditReport:
    """Structured result of a permission-friction analysis pass."""

    findings: list[Finding] = field(default_factory=list)
    hygiene: list[HygieneFinding] = field(default_factory=list)
    proposals: list[str] = field(default_factory=list)

    def render_markdown(self) -> str:
        buf = io.StringIO()
        write_output(
            findings=self.findings,
            hygiene=self.hygiene,
            proposals=self.proposals,
            out=buf,
        )
        return buf.getvalue()


def build_audit_report(
    *,
    transcript: str,
    settings_path: Path,
    skills_dir: Path | None = None,
    tools_dir: Path | None = None,
    project_root: str | None = None,
) -> AuditReport:
    """Build a permission-friction AuditReport from raw transcript text.

    Mirrors the composition in
    `dev10x.skills.audit.analyze_permissions.main` but exposes the
    result as data instead of writing to stdout/file.
    """

    calls = parse_tool_calls(text=transcript)
    rules = parse_allow_rules(settings_path=str(settings_path))
    additional_dirs = parse_additional_directories(settings_path=str(settings_path))

    findings = _analyze_permissions(calls=calls, rules=rules)
    findings = count_nuisance_patterns(findings=findings)

    # GH-979 (H6): when an MCP caller bound the worktree via use_cwd, default
    # the project root to it at this seam. permissions_model.detect_known_friction
    # applies the same effective_cwd() fallback for standalone CLI callers that
    # pass None.
    extra = detect_known_friction(
        calls=calls,
        additional_dirs=additional_dirs,
        project_root=project_root if project_root is not None else effective_cwd(),
    )
    base_count = len(findings)
    findings.extend(
        replace(finding, index=base_count + offset)
        for offset, finding in enumerate(extra, start=1)
    )

    # GH-507: surface PreToolUse hook denials hidden in tool-result blocks
    # so MCP callers see HOOK_DENIAL findings, matching the standalone CLI
    # path in dev10x.skills.audit.analyze_permissions.main.
    denials = detect_hook_denials(text=transcript)
    base_count = len(findings)
    findings.extend(
        replace(finding, index=base_count + offset)
        for offset, finding in enumerate(denials, start=1)
    )

    skills_root = str(skills_dir) if skills_dir else str(ClaudeDir.skills_dir())
    tools_root = str(tools_dir) if tools_dir else str(ClaudeDir.tools_dir())
    hygiene = audit_script_hygiene(skills_dir=skills_root, tools_dir=tools_root)

    proposals = propose_allow_rules(findings=findings)

    return AuditReport(findings=findings, hygiene=hygiene, proposals=proposals)
