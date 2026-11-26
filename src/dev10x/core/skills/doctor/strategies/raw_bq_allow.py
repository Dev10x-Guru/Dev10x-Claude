"""Strategy: raw-bq-allow (GH-1633).

A ``Bash(bq:*)`` or ``Bash(bq query:*)`` allow auto-approves every
BigQuery statement the agent types, writes included. DX004 refuses the
writes at the hook, but the read-only path is now the ``dev10x-db:bq``
skill and its ``bq_*`` MCP tools, so the raw allow only widens the
surface. The rule lives in the user's own settings, which the plugin
never edits: this strategy reports it and proposes the move to deny.

Rules for a single read-only verb other than ``query`` (``Bash(bq ls:*)``,
``Bash(bq show:*)``) cannot run SQL or write, so they are left alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dev10x.core.domain.common.allow_rule import AllowRule, AllowRuleLoader
from dev10x.core.domain.rules.read_only_sql import BQ_READ_ONLY_VERBS
from dev10x.core.skills.doctor.strategy import Context, Finding, Remediation, Strategy

STRATEGY_ID = "raw-bq-allow"

_BQ_RULE_RE = re.compile(r"^bq(?P<rest>$|[\s:*].*)$", re.DOTALL)
_HARMLESS_VERBS = BQ_READ_ONLY_VERBS - {"query"}


@dataclass(frozen=True)
class RawBqRemediation:
    rule: str
    settings_path: str

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=self.settings_path,
            action={
                "remove": {"permissions.allow": self.rule},
                "add": {"permissions.deny": self.rule},
                "reason": (
                    "Read BigQuery through dev10x-db:bq (mcp__plugin_dev10x_db__bq_*) "
                    "instead of raw bq."
                ),
            },
        )


def runs_raw_bq(*, rule: str) -> bool:
    parsed = AllowRule.parse(rule)
    if parsed.tool != "Bash":
        return False
    match = _BQ_RULE_RE.match(parsed.pattern.strip())
    if not match:
        return False
    verb = match["rest"].strip().split(" ", 1)[0].removesuffix(":*").removesuffix("*")
    return verb not in _HARMLESS_VERBS


def detect(context: Context) -> list[Finding]:
    findings: list[Finding] = []
    for path in context.settings_paths:
        if not path.exists():
            continue
        for rule in AllowRuleLoader.load(path):
            if not runs_raw_bq(rule=rule):
                continue
            findings.append(
                Finding(
                    strategy_id=STRATEGY_ID,
                    severity="suggestion",
                    location=str(path),
                    evidence=(
                        f"``{rule}`` auto-approves raw bq, including statements "
                        "that write; only the DX004 hook stands between it and "
                        "a DELETE or --destination_table."
                    ),
                    proposed_fix=(
                        f"Move ``{rule}`` from permissions.allow to permissions.deny "
                        f"in {path}, and read BigQuery through dev10x-db:bq."
                    ),
                    data=RawBqRemediation(rule=rule, settings_path=str(path)),
                )
            )
    return findings


def remediate(finding: Finding) -> Remediation:
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Report Bash(bq …) allows that approve raw BigQuery commands, now that "
        "dev10x-db:bq reads BigQuery through validated read-only MCP tools."
    ),
    detect=detect,
    remediate=remediate,
)
