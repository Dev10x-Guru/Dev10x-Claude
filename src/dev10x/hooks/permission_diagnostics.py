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

import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir


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

    def has_any_match(self) -> bool:
        return any(m.is_matched() for m in self.matches)


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
    tool_name = raw.get("tool_name", "")
    tool_input = raw.get("tool_input", {})

    if not tool_name:
        return None

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not command:
            return None
        return f"Bash({command})"

    if tool_name in ("Write", "Read", "Edit"):
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return None
        return f"{tool_name}({file_path})"

    if tool_name.startswith("mcp__"):
        return tool_name

    return f"{tool_name}()"


def _load_allow_rules(path: Path) -> list[str] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    permissions = data.get("permissions", {})
    allow = permissions.get("allow")
    if allow is None:
        return None
    if not isinstance(allow, list):
        return None
    return allow


class PermissionResolutionPolicy:
    """Encapsulates how an allow-rule string is matched against a tool signature.

    Lives as a named class so the matching semantics — MCP tools by
    fnmatch over the whole signature, Bash rules by tool+pattern with
    ``:*`` prefix expansion — can be unit-tested and extended without
    touching ``diagnose()``.
    """

    @staticmethod
    def matches(*, signature: str, rule: str) -> bool:
        if signature.startswith("mcp__"):
            return fnmatch.fnmatch(name=signature, pat=rule)

        paren_idx = rule.find("(")
        if paren_idx == -1:
            return fnmatch.fnmatch(name=signature, pat=rule)

        rule_tool = rule[:paren_idx]
        rule_pattern = rule[paren_idx + 1 :].rstrip(")")

        sig_paren_idx = signature.find("(")
        if sig_paren_idx == -1:
            return False

        sig_tool = signature[:sig_paren_idx]
        sig_value = signature[sig_paren_idx + 1 :].rstrip(")")

        if rule_tool != sig_tool:
            return False

        if rule_pattern.endswith(":*"):
            prefix = rule_pattern[:-2]
            return sig_value == prefix or sig_value.startswith(prefix + " ")

        return fnmatch.fnmatch(name=sig_value, pat=rule_pattern)

    @classmethod
    def find_matching(cls, *, signature: str, rules: list[str]) -> str | None:
        for rule in rules:
            if cls.matches(signature=signature, rule=rule):
                return rule
        return None


def _matches_rule(*, signature: str, rule: str) -> bool:
    return PermissionResolutionPolicy.matches(signature=signature, rule=rule)


def _find_matching_rule(*, signature: str, rules: list[str]) -> str | None:
    return PermissionResolutionPolicy.find_matching(signature=signature, rules=rules)


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
        cwd = os.getcwd()

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
    if signature.startswith("mcp__"):
        last_sep = signature.rfind("__")
        if last_sep > 0:
            prefix = signature[:last_sep]
            return f"{prefix}__*"
        return signature

    paren_idx = signature.find("(")
    if paren_idx == -1:
        return signature

    tool = signature[:paren_idx]
    value = signature[paren_idx + 1 :].rstrip(")")

    if tool == "Bash":
        first_space = value.find(" ")
        if first_space > 0:
            return f"Bash({value[:first_space]}:*)"
        return f"Bash({value}:*)"

    if tool in ("Write", "Read", "Edit"):
        path = Path(value)
        parent = str(path.parent)
        return f"{tool}({parent}/**)"

    return signature


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
