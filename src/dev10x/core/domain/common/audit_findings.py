"""Machine-readable permission-auditor findings (GH-1631).

The ``permission-auditor`` agent ends its prose report with one JSON
block of findings; ``dev10x:permission-audit-apply`` applies them one
at a time. This module is the contract between the two: it parses that
block, rejects a finding the apply skill could not act on, and narrows
the list to a severity ceiling for the unattended bulk path.

Schema reference: ``references/agents/permission-auditor/finding-schema.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from dev10x.core.domain.common.result import ErrorResult, Result, err, ok


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @property
    def rank(self) -> int:
        """Declaration order is severity order: CRITICAL ranks 0."""
        return list(Severity).index(self)


class FixAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    MANUAL = "manual"


class RuleList(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class ProposedFix:
    action: FixAction
    rule_list: RuleList | None
    rule: str | None
    replacement: str | None
    note: str


@dataclass(frozen=True)
class AuditFinding:
    id: str
    title: str
    severity: Severity
    file: str
    line: int | None
    current_rule: str | None
    proposed_fix: ProposedFix
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        fix = data.pop("proposed_fix")
        fix["list"] = fix.pop("rule_list")
        data["proposed_fix"] = fix
        return data


@dataclass(frozen=True)
class FindingSelection:
    selected: tuple[AuditFinding, ...]
    excluded_by_severity: tuple[AuditFinding, ...]


def _require_str(*, entry: dict, key: str, where: str) -> Result[str]:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        return err(f"{where}: '{key}' must be a non-empty string")
    return ok(value)


def _optional_str(*, entry: dict, key: str, where: str) -> Result[str | None]:
    value = entry.get(key)
    if value is None:
        return ok(None)
    if not isinstance(value, str):
        return err(f"{where}: '{key}' must be a string or null")
    return ok(value)


def _parse_fix(*, raw: object, where: str) -> Result[ProposedFix]:
    if not isinstance(raw, dict):
        return err(f"{where}: 'proposed_fix' must be an object")
    try:
        action = FixAction(str(raw.get("action")))
    except ValueError:
        allowed = ", ".join(action.value for action in FixAction)
        return err(f"{where}: proposed_fix.action must be one of {allowed}")
    rule_list: RuleList | None = None
    if raw.get("list") is not None:
        try:
            rule_list = RuleList(raw["list"])
        except ValueError:
            return err(f"{where}: proposed_fix.list must be allow, deny or ask")
    strings: dict[str, str | None] = {}
    for key in ("rule", "replacement", "note"):
        value = _optional_str(entry=raw, key=key, where=f"{where} proposed_fix")
        if isinstance(value, ErrorResult):
            return value
        strings[key] = value.value
    if action is not FixAction.MANUAL and (rule_list is None or not strings["rule"]):
        return err(f"{where}: a '{action.value}' fix needs 'list' and 'rule'")
    if action is FixAction.REPLACE and not strings["replacement"]:
        return err(f"{where}: a 'replace' fix needs 'replacement'")
    return ok(
        ProposedFix(
            action=action,
            rule_list=rule_list,
            rule=strings["rule"],
            replacement=strings["replacement"],
            note=strings["note"] or "",
        )
    )


def _parse_finding(*, raw: object, index: int) -> Result[AuditFinding]:
    where = f"finding[{index}]"
    if not isinstance(raw, dict):
        return err(f"{where}: must be an object")
    required: dict[str, str] = {}
    for key in ("id", "title", "file", "rationale"):
        value = _require_str(entry=raw, key=key, where=where)
        if isinstance(value, ErrorResult):
            return value
        required[key] = value.value
    try:
        severity = Severity(str(raw.get("severity", "")).upper())
    except ValueError:
        return err(f"{where}: severity must be CRITICAL, HIGH, MEDIUM or LOW")
    line = raw.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int)):
        return err(f"{where}: 'line' must be an integer or null")
    current_rule = _optional_str(entry=raw, key="current_rule", where=where)
    if isinstance(current_rule, ErrorResult):
        return current_rule
    fix = _parse_fix(raw=raw.get("proposed_fix"), where=where)
    if isinstance(fix, ErrorResult):
        return fix
    return ok(
        AuditFinding(
            id=required["id"],
            title=required["title"],
            severity=severity,
            file=required["file"],
            line=line,
            current_rule=current_rule.value,
            proposed_fix=fix.value,
            rationale=required["rationale"],
        )
    )


def parse_findings(*, payload: object) -> Result[tuple[AuditFinding, ...]]:
    """Parse the auditor's ``{"findings": [...]}`` block.

    The whole block is rejected on the first malformed finding: applying
    a partial list would silently drop the finding that failed to parse,
    which is the over-reach-by-omission GH-1631 exists to prevent.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        return err("payload must be an object with a 'findings' list")
    findings: list[AuditFinding] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload["findings"]):
        parsed = _parse_finding(raw=raw, index=index)
        if isinstance(parsed, ErrorResult):
            return parsed
        if parsed.value.id in seen:
            return err(f"finding[{index}]: duplicate id '{parsed.value.id}'")
        seen.add(parsed.value.id)
        findings.append(parsed.value)
    return ok(tuple(findings))


def select_findings(
    *,
    findings: tuple[AuditFinding, ...],
    severity_max: Severity | None,
) -> FindingSelection:
    """Keep findings from CRITICAL down to ``severity_max``, most severe first.

    ``severity_max=HIGH`` keeps CRITICAL and HIGH and excludes MEDIUM and
    LOW — the approved-scope ceiling whose absence let a MEDIUM finding
    ride along with a CRITICAL+HIGH approval in GH-965. ``None`` keeps
    everything.
    """
    ordered = tuple(sorted(findings, key=lambda finding: finding.severity.rank))
    if severity_max is None:
        return FindingSelection(selected=ordered, excluded_by_severity=())
    return FindingSelection(
        selected=tuple(f for f in ordered if f.severity.rank <= severity_max.rank),
        excluded_by_severity=tuple(f for f in ordered if f.severity.rank > severity_max.rank),
    )


__all__ = [
    "AuditFinding",
    "FindingSelection",
    "FixAction",
    "ProposedFix",
    "RuleList",
    "Severity",
    "parse_findings",
    "select_findings",
]
