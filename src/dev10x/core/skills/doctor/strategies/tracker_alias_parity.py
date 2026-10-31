"""Strategy: tracker-alias-parity (GH-1668).

One tracker's tools are reachable under several MCP server names
(``mcp__claude_ai_Linear__*``, ``mcp__linear-server__*``, ...). Rules name
a server, so a rule written for one name says nothing about the others:
a tool allowed under one name prompts under another, and a ``delete_*``
deny on one name leaves the same tool open under the next.

Report-only. Three finding kinds:

- ``parity``: a tracker tool allowed under some alias but not all.
- ``delete-allowed``: a ``delete_*`` tool allowed under any alias without
  a matching deny (GH-204).
- ``dead-bash-rule``: ``Bash(mcp__...)`` wraps an MCP tool name in a shell
  matcher, which can never match a tool call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from dev10x.domain.common.tracker_choice import TRACKER_SERVER_ALIASES, Tracker
from dev10x.skills.doctor.strategy import Context, Finding, Remediation, Strategy

STRATEGY_ID = "tracker-alias-parity"
_MCP_PREFIX = "mcp__"
_DEAD_PREFIX = "Bash(mcp__"
_DELETE_TOOL_PREFIX = "delete_"
_WILDCARD = "*"


@dataclass(frozen=True)
class AliasParityRemediation:
    """Remediation payload for a tracker-alias-parity finding."""

    kind: str
    rules: tuple[str, ...]

    def to_remediation(self, *, finding: Finding) -> Remediation:
        target = "permissions.deny" if self.kind == "delete-allowed" else "permissions.allow"
        return Remediation(
            kind="edit_settings",
            target=target,
            action={"finding": self.kind, "rules": list(self.rules)},
        )


def _read_permissions(*, path: Path, key: str) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    permissions = data.get("permissions") if isinstance(data, dict) else None
    rules = permissions.get(key) if isinstance(permissions, dict) else None
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, str)]


def _tools_by_alias(*, rules: list[str], aliases: tuple[str, ...]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {alias: set() for alias in aliases}
    for alias in aliases:
        head = f"{_MCP_PREFIX}{alias}__"
        found[alias] = {rule.removeprefix(head) for rule in rules if rule.startswith(head)}
    return found


def _is_denied(*, tool: str, patterns: set[str]) -> bool:
    return any(fnmatchcase(tool, pattern) for pattern in patterns)


def _finding(
    *,
    path: Path,
    kind: str,
    evidence: str,
    fix: str,
    rules: tuple[str, ...],
) -> Finding:
    return Finding(
        strategy_id=STRATEGY_ID,
        severity="drift" if kind == "parity" else "critical",
        location=str(path),
        evidence=evidence,
        proposed_fix=fix,
        data=AliasParityRemediation(kind=kind, rules=rules),
    )


def _tracker_findings(
    *,
    path: Path,
    tracker: Tracker,
    aliases: tuple[str, ...],
    allow: list[str],
    deny: list[str],
) -> list[Finding]:
    allowed = _tools_by_alias(rules=allow, aliases=aliases)
    denied = _tools_by_alias(rules=deny, aliases=aliases)
    every_tool = set().union(*allowed.values()) - {_WILDCARD}
    findings: list[Finding] = []
    for tool in sorted(every_tool):
        holders = [alias for alias in aliases if tool in allowed[alias]]
        missing = [alias for alias in aliases if tool not in allowed[alias]]
        if tool.startswith(_DELETE_TOOL_PREFIX):
            open_under = tuple(
                f"{_MCP_PREFIX}{alias}__{tool}"
                for alias in holders
                if not _is_denied(tool=tool, patterns=denied[alias])
            )
            if open_under:
                findings.append(
                    _finding(
                        path=path,
                        kind="delete-allowed",
                        evidence=(
                            f"{tracker.value} destructive tool allowed: {', '.join(open_under)}"
                        ),
                        fix="Remove the allow and deny the tool under every alias (GH-204).",
                        rules=open_under,
                    )
                )
            continue
        if missing:
            absent = tuple(f"{_MCP_PREFIX}{alias}__{tool}" for alias in missing)
            findings.append(
                _finding(
                    path=path,
                    kind="parity",
                    evidence=(
                        f"{tracker.value} tool `{tool}` is allowed under "
                        f"{', '.join(holders)} but not {', '.join(missing)}"
                    ),
                    fix="Re-run `dev10x permission ensure-base` or allow: " + ", ".join(absent),
                    rules=absent,
                )
            )
    return findings


def _dead_rule_findings(*, path: Path, allow: list[str]) -> list[Finding]:
    return [
        _finding(
            path=path,
            kind="dead-bash-rule",
            evidence=f"`{rule}` wraps an MCP tool name in Bash() and can never match",
            fix=f"Replace it with `{rule.removeprefix('Bash(').split(' ')[0].rstrip(')')}`.",
            rules=(rule,),
        )
        for rule in allow
        if rule.startswith(_DEAD_PREFIX)
    ]


def detect(context: Context) -> list[Finding]:
    findings: list[Finding] = []
    for path in context.settings_paths:
        if not path.exists():
            continue
        allow = _read_permissions(path=path, key="allow")
        deny = _read_permissions(path=path, key="deny")
        for tracker, aliases in TRACKER_SERVER_ALIASES.items():
            findings.extend(
                _tracker_findings(
                    path=path, tracker=tracker, aliases=aliases, allow=allow, deny=deny
                )
            )
        findings.extend(_dead_rule_findings(path=path, allow=allow))
    return findings


def remediate(finding: Finding) -> Remediation:
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Report tracker MCP tools allowed under one server-name alias but "
        "not another, delete_* tools allowed under any alias, and "
        "Bash(mcp__...) dead rules."
    ),
    detect=detect,
    remediate=remediate,
)
