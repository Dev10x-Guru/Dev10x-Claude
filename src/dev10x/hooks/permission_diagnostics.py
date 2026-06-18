"""Permission diagnostics for the PermissionDenied hook.

When a user is prompted for permission on a tool call they expected to be
pre-approved, this module diagnoses *why* the allow rule didn't match by
loading all settings files in precedence order and matching the tool call
against each file's permissions.allow list independently.

Claude Code settings precedence (higher overrides lower):
  1. Managed settings (cannot be overridden)
  2. Command line arguments
  3. Project local (.claude/settings.local.json)
  4. Project shared (.claude/settings.json)
  5. User settings (~/.claude/settings.json)

Each level **replaces** the previous level entirely — there is no array
merge/union. A rule in level 5 is invisible if level 3 defines its own
permissions.allow list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.allow_rule import AllowRule, AllowRuleLoader
from dev10x.domain.common.tool_signature import ToolSignature
from dev10x.subprocess_utils import effective_cwd


@dataclass(frozen=True)
class SettingsFile:
    label: str
    path: Path
    precedence: int


@dataclass(frozen=True)
class RuleMatch:
    settings_file: SettingsFile
    matching_rule: str | None
    has_allow_list: bool

    def is_matched(self) -> bool:
        return self.matching_rule is not None

    def is_unmatched_with_allow_list(self) -> bool:
        return self.has_allow_list and self.matching_rule is None


@dataclass(frozen=True)
class DiagnosticResult:
    tool_signature: str
    matches: list[RuleMatch]
    diagnosis: str
    fix_suggestion: str

    def matched(self) -> list[RuleMatch]:
        return [m for m in self.matches if m.is_matched()]


SETTINGS_PRECEDENCE: list[SettingsFile] = [
    SettingsFile(
        label="project local",
        path=Path(".claude/settings.local.json"),
        precedence=3,
    ),
    SettingsFile(
        label="project shared",
        path=Path(".claude/settings.json"),
        precedence=4,
    ),
    SettingsFile(
        label="user settings",
        path=ClaudeDir.settings_json(),
        precedence=5,
    ),
]


def extract_tool_signature(raw: dict[str, Any]) -> str | None:
    sig = ToolSignature.from_hook_input(raw)
    if sig is None:
        return None
    return str(sig)


def _load_allow_rules(path: Path) -> list[str] | None:
    return AllowRuleLoader.load_optional(path=path)


def _matches_rule(*, signature: str, rule: str) -> bool:
    return AllowRule.parse(rule).matches(signature)


def _find_matching_rule(*, signature: str, rules: list[str]) -> str | None:
    for rule in rules:
        if AllowRule.parse(rule).matches(signature):
            return rule
    return None


def _resolve_settings_files(*, cwd: str) -> list[SettingsFile]:
    resolved: list[SettingsFile] = []
    for sf in SETTINGS_PRECEDENCE:
        if sf.path.is_absolute():
            resolved.append(sf)
        else:
            abs_path = Path(cwd) / sf.path if cwd else Path.cwd() / sf.path
            resolved.append(
                SettingsFile(
                    label=sf.label,
                    path=abs_path,
                    precedence=sf.precedence,
                )
            )
    return resolved


def diagnose(raw: dict[str, Any], *, cwd: str = "") -> DiagnosticResult | None:
    signature = extract_tool_signature(raw=raw)
    if signature is None:
        return None

    if not cwd:
        cwd = effective_cwd() or os.getcwd()

    settings_files = _resolve_settings_files(cwd=cwd)
    matches: list[RuleMatch] = []
    winning_file: SettingsFile | None = None

    for sf in settings_files:
        rules = _load_allow_rules(path=sf.path)
        if rules is None:
            matches.append(
                RuleMatch(
                    settings_file=sf,
                    matching_rule=None,
                    has_allow_list=False,
                )
            )
            continue

        matching_rule = _find_matching_rule(signature=signature, rules=rules)
        matches.append(
            RuleMatch(
                settings_file=sf,
                matching_rule=matching_rule,
                has_allow_list=True,
            )
        )

        if winning_file is None and rules:
            winning_file = sf

    diagnosis = _build_diagnosis(
        matches=matches,
        winning_file=winning_file,
    )
    fix_suggestion = _build_fix_suggestion(
        signature=signature,
        matches=matches,
        winning_file=winning_file,
    )

    return DiagnosticResult(
        tool_signature=signature,
        matches=matches,
        diagnosis=diagnosis,
        fix_suggestion=fix_suggestion,
    )


def _build_diagnosis(
    *,
    matches: list[RuleMatch],
    winning_file: SettingsFile | None,
) -> str:
    files_with_match = [m for m in matches if m.is_matched()]
    files_with_allow_list = [m for m in matches if m.has_allow_list]
    files_without_match = [m for m in matches if m.is_unmatched_with_allow_list()]

    if not files_with_match:
        return "No matching allow rule found in any settings file."

    if winning_file is not None and files_without_match:
        shadowed = [m for m in files_with_match if m.settings_file != winning_file]
        if shadowed:
            shadowed_labels = ", ".join(m.settings_file.label for m in shadowed)
            return (
                f"{winning_file.label} defines its own permissions.allow list "
                f"which overrides lower-precedence files. The matching rule "
                f"exists in {shadowed_labels} but is not inherited — "
                f"Claude Code uses replacement semantics, not merge."
            )

    overriding = [
        m
        for m in files_with_allow_list
        if m.matching_rule is None
        and winning_file is not None
        and m.settings_file.precedence < winning_file.precedence
    ]
    if overriding:
        labels = ", ".join(m.settings_file.label for m in overriding)
        return (
            f"{labels} defines permissions.allow without this rule, "
            f"overriding the matching rule in a lower-precedence file."
        )

    return "Rule exists but may not match due to pattern syntax."


def _build_fix_suggestion(
    *,
    signature: str,
    matches: list[RuleMatch],
    winning_file: SettingsFile | None,
) -> str:
    files_with_match = [m for m in matches if m.is_matched()]

    if not files_with_match:
        if winning_file:
            rule = _suggest_rule(signature=signature)
            return f"Add `{rule}` to {winning_file.label} ({winning_file.path})"
        return f"Add an allow rule for `{signature}` to your settings."

    if winning_file is not None:
        winning_match = next(
            (m for m in matches if m.settings_file == winning_file),
            None,
        )
        if winning_match is not None and winning_match.matching_rule is None:
            matched_rule = files_with_match[0].matching_rule
            return f"Add `{matched_rule}` to {winning_file.label} ({winning_file.path})"

    return ""


def _suggest_rule(*, signature: str) -> str:
    paren_idx = signature.find("(")
    if paren_idx == -1:
        # MCP tool names have no parens — delegate via ToolSignature directly.
        # Non-MCP bare names (no parens) return unchanged (original behaviour).
        tool = signature
        value = ""
    else:
        tool = signature[:paren_idx]
        value = signature[paren_idx + 1 :].rstrip(")")
    sig = ToolSignature(tool=tool, value=value)
    result = sig.suggest_rule()
    # For non-MCP bare names the VO returns "Tool()" which differs from the
    # original "return signature" contract — preserve the original output.
    if paren_idx == -1 and not sig.tool.startswith("mcp__"):
        return signature
    return result


def format_diagnostic(result: DiagnosticResult) -> str:
    lines: list[str] = []
    lines.append(f"Permission prompt for: {result.tool_signature}")
    lines.append("")
    lines.append("Matching rules found:")

    for m in result.matches:
        if not m.has_allow_list:
            status = "(no permissions.allow)"
            lines.append(f"  {m.settings_file.label:25s} {status}")
        elif m.matching_rule:
            lines.append(f"  {m.settings_file.label:25s} {m.matching_rule} MATCH")
        else:
            lines.append(f"  {m.settings_file.label:25s} (no matching rule) NOT COVERED")

    lines.append("")
    lines.append(f"Diagnosis: {result.diagnosis}")

    if result.fix_suggestion:
        lines.append(f"Fix: {result.fix_suggestion}")

    return "\n".join(lines)
