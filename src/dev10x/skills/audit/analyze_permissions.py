#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deterministic Phase 4 permission friction analysis for skill-audit.

Thin CLI adapter (GH-244, I1 / ADR-0008). The parsers, classifiers,
hygiene auditor, and report writer now live in
``dev10x.audit.permissions_model`` — the audit context owns the analysis
logic. This module re-exports those names for backward compatibility and
provides the ``main`` entry point used by the skill-audit Bash pipeline.

Usage:
    analyze-permissions.py <transcript.md> [settings.json] [output.md]

If settings.json is omitted, uses ~/.claude/settings.local.json.
If output.md is omitted, writes to stdout.
"""

import os
import sys
from pathlib import Path

from dev10x.audit.permissions_model import (
    ALLOW_RULE_RE,
    CHAIN_RE,
    COMMENT_PREFIX_RE,
    DANGEROUS_COMMANDS,
    ENV_PREFIX_RE,
    EXIT_FALSE_POSITIVE_RE,
    GIT_C_RE,
    HEREDOC_RE,
    HOOK_BLOCK_RE,
    MKTMP_PATH_RE,
    MULTI_WORD_COMMANDS,
    PERMISSION_DENY_RE,
    PERMISSION_TOOLS,
    SUBSHELL_RE,
    TOOL_INPUT_BLOCK_RE,
    TOOL_RE,
    TOOL_RESULT_BLOCK_RE,
    TURN_RE,
    Finding,
    HygieneFinding,
    ToolCall,
    analyze_permissions,
    audit_script_hygiene,
    classify_toxicity,
    classify_unmatched,
    count_nuisance_patterns,
    detect_hook_denials,
    detect_known_friction,
    matches_allow_rule,
    parse_additional_directories,
    parse_allow_rules,
    parse_tool_calls,
    propose_allow_rules,
    write_output,
)

__all__ = [
    "ALLOW_RULE_RE",
    "CHAIN_RE",
    "COMMENT_PREFIX_RE",
    "DANGEROUS_COMMANDS",
    "ENV_PREFIX_RE",
    "EXIT_FALSE_POSITIVE_RE",
    "GIT_C_RE",
    "HEREDOC_RE",
    "HOOK_BLOCK_RE",
    "MKTMP_PATH_RE",
    "MULTI_WORD_COMMANDS",
    "PERMISSION_DENY_RE",
    "PERMISSION_TOOLS",
    "SUBSHELL_RE",
    "TOOL_INPUT_BLOCK_RE",
    "TOOL_RE",
    "TOOL_RESULT_BLOCK_RE",
    "TURN_RE",
    "Finding",
    "HygieneFinding",
    "ToolCall",
    "analyze_permissions",
    "audit_script_hygiene",
    "classify_toxicity",
    "classify_unmatched",
    "count_nuisance_patterns",
    "detect_hook_denials",
    "detect_known_friction",
    "matches_allow_rule",
    "parse_additional_directories",
    "parse_allow_rules",
    "parse_tool_calls",
    "propose_allow_rules",
    "write_output",
    "main",
]


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    transcript_path = sys.argv[1]
    settings_path = (
        sys.argv[2]
        if len(sys.argv) >= 3 and sys.argv[2].endswith(".json")
        else os.path.expanduser("~/.claude/settings.local.json")
    )
    output_path = None
    if len(sys.argv) >= 3 and sys.argv[-1].endswith(".md"):
        output_path = sys.argv[-1]

    transcript = Path(transcript_path).read_text()
    calls = parse_tool_calls(text=transcript)
    rules = parse_allow_rules(settings_path=settings_path)
    additional_dirs = parse_additional_directories(settings_path=settings_path)
    findings = analyze_permissions(calls=calls, rules=rules)
    findings = count_nuisance_patterns(findings=findings)
    extra = detect_known_friction(calls=calls, additional_dirs=additional_dirs)
    # Renumber the extra findings to continue past the base ones
    base_count = len(findings)
    for offset, finding in enumerate(extra, start=1):
        finding.index = base_count + offset
    findings.extend(extra)

    denials = detect_hook_denials(text=transcript)
    base_count = len(findings)
    for offset, finding in enumerate(denials, start=1):
        finding.index = base_count + offset
    findings.extend(denials)

    skills_dir = os.path.expanduser("~/.claude/skills")
    tools_dir = os.path.expanduser("~/.claude/tools")
    hygiene = audit_script_hygiene(skills_dir=skills_dir, tools_dir=tools_dir)

    proposals = propose_allow_rules(findings=findings)

    if output_path:
        with open(output_path, "w") as f:
            write_output(findings=findings, hygiene=hygiene, proposals=proposals, out=f)
        print(f"Phase 4 output written to {output_path}", file=sys.stderr)
    else:
        write_output(findings=findings, hygiene=hygiene, proposals=proposals, out=sys.stdout)


if __name__ == "__main__":
    main()
