"""Strategy: unmatchable-star-prefix (GH-1503).

A Bash rule with a ``*`` before its trailing ``:*`` is a literal prefix:
it never matches, and Claude Code warns about it at every startup. In an
allow list that is noise. In a deny or ask list it is a guardrail that
reads as present and fires on nothing, which is why those are critical.

Detection and the proposed fix are ``star_prefix``'s, the same pass
``dev10x permission clean`` applies, so the doctor names exactly what the
fix will drop or rewrite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.skills.doctor.strategy import Context, Finding, Remediation, Severity, Strategy
from dev10x.skills.permission.star_prefix import StarPrefixFix, repair_star_prefix

STRATEGY_ID = "unmatchable-star-prefix"

_APPLY = "Run `dev10x permission clean` to apply it (a backup is written first)."


@dataclass(frozen=True)
class StarPrefixRemediation:
    """Remediation payload: one rule to drop, rewrite, or prune."""

    settings_path: str
    target: str
    rule: str
    replacement: str | None
    operation: str

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=self.target,
            action={
                "path": self.settings_path,
                "operation": self.operation,
                "rule": self.rule,
                "replacement": self.replacement,
            },
        )


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _operation(fix: StarPrefixFix) -> str:
    if fix.dropped:
        return "drop"
    return "prune" if fix.pruned else "rewrite"


def _finding(*, path: Path, fix: StarPrefixFix) -> Finding:
    guardrail = fix.list_name in ("deny", "ask")
    severity: Severity = "critical" if guardrail and not fix.pruned else "drift"
    if fix.dropped:
        proposed = (
            f"Drop ``{fix.before}``. Do not rewrite it to the space form: that "
            f"turns a grant that never matched into a real wildcard. {_APPLY}"
        )
    elif fix.pruned:
        proposed = f"Remove ``{fix.before}``; ``{fix.after}`` already covers it. {_APPLY}"
    else:
        proposed = f"Rewrite to ``{fix.after}``, the form Claude Code suggests. {_APPLY}"
    return Finding(
        strategy_id=STRATEGY_ID,
        severity=severity,
        location=f"{path}:permissions.{fix.list_name}",
        evidence=(
            f"``{fix.before}`` puts a `*` before `:*`, so Claude Code reads it as a "
            f"literal prefix and it never matches — this {fix.list_name} rule "
            + ("guards nothing." if guardrail else "grants nothing.")
        ),
        proposed_fix=proposed,
        data=StarPrefixRemediation(
            settings_path=str(path),
            target=f"permissions.{fix.list_name}",
            rule=fix.before,
            replacement=fix.after,
            operation=_operation(fix),
        ),
    )


def detect(context: Context) -> list[Finding]:
    """Report every `*`-before-`:*` Bash rule in every settings layer."""
    findings: list[Finding] = []
    for path in dict.fromkeys(context.settings_paths):
        data = _load(path)
        if data is None:
            continue
        _, repair = repair_star_prefix(data)
        findings.extend(_finding(path=path, fix=fix) for fix in repair.fixes)
    return findings


def remediate(finding: Finding) -> Remediation:
    """Propose the drop, rewrite, or prune for one unmatchable rule."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Flag Bash rules with a `*` before the trailing `:*`. They never match, "
        "so an allow is noise and a deny or ask guards nothing (GH-1503)."
    ),
    detect=detect,
    remediate=remediate,
)
