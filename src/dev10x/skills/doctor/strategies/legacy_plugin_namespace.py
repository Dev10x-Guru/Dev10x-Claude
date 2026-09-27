"""Strategy: legacy-plugin-namespace (GH-1501).

GH-1499 renamed the plugin ``Dev10x`` -> ``dev10x``. A rule still spelled
``Skill(Dev10x:…)`` or ``mcp__plugin_Dev10x_…`` names a tool that no longer
exists, so it matches nothing. On an allow rule that costs a prompt; on a
deny or ask rule it is a guardrail that reads as present in the file and
guards nothing — which is why those are critical, not drift.

The detection is ``legacy_namespace``'s, the same pass
``dev10x permission clean`` applies, so the doctor reports exactly the
moves the fix will make.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.skills.doctor.strategy import Context, Finding, Remediation, Severity, Strategy
from dev10x.skills.permission.legacy_namespace import (
    CURRENT_PLUGIN_ID,
    LEGACY_PLUGIN_ID,
    RuleMove,
    migrate_legacy_namespace,
)

STRATEGY_ID = "legacy-plugin-namespace"

_APPLY = "Run `dev10x permission clean` to apply it (a backup is written first)."


@dataclass(frozen=True)
class LegacyNamespaceRemediation:
    """Remediation payload: one rule or plugin id to move."""

    settings_path: str
    target: str
    legacy: str
    current: str
    pruned: bool

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=self.target,
            action={
                "path": self.settings_path,
                "operation": "prune" if self.pruned else "rewrite",
                "rule": self.legacy,
                "replacement": self.current,
            },
        )


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _rule_finding(*, path: Path, move: RuleMove) -> Finding:
    guardrail = move.list_name in ("deny", "ask")
    severity: Severity = "critical" if guardrail and not move.pruned else "drift"
    consequence = (
        f"this {move.list_name} rule guards nothing since the rename"
        if guardrail
        else "this allow rule grants nothing since the rename"
    )
    if move.pruned:
        consequence = f"a stale duplicate: ``{move.current}`` is already in the list"
    return Finding(
        strategy_id=STRATEGY_ID,
        severity=severity,
        location=f"{path}:permissions.{move.list_name}",
        evidence=f"``{move.legacy}`` uses the pre-GH-1499 ``Dev10x`` spelling — {consequence}.",
        proposed_fix=(
            f"Remove ``{move.legacy}``. {_APPLY}"
            if move.pruned
            else f"Rewrite to ``{move.current}``. {_APPLY}"
        ),
        data=LegacyNamespaceRemediation(
            settings_path=str(path),
            target=f"permissions.{move.list_name}",
            legacy=move.legacy,
            current=move.current,
            pruned=move.pruned,
        ),
    )


def _plugin_id_finding(*, path: Path, pruned: bool) -> Finding:
    return Finding(
        strategy_id=STRATEGY_ID,
        severity="drift",
        location=f"{path}:enabledPlugins",
        evidence=(
            f"``{LEGACY_PLUGIN_ID}`` names the plugin's pre-GH-1499 install id; "
            f"the plugin now installs as ``{CURRENT_PLUGIN_ID}``."
        ),
        proposed_fix=(
            f"Remove the ``{LEGACY_PLUGIN_ID}`` key. {_APPLY}"
            if pruned
            else f"Rename the key to ``{CURRENT_PLUGIN_ID}``, keeping its value. {_APPLY}"
        ),
        data=LegacyNamespaceRemediation(
            settings_path=str(path),
            target="enabledPlugins",
            legacy=LEGACY_PLUGIN_ID,
            current=CURRENT_PLUGIN_ID,
            pruned=pruned,
        ),
    )


def detect(context: Context) -> list[Finding]:
    """Report every pre-rename spelling in every settings layer."""
    findings: list[Finding] = []
    for path in dict.fromkeys(context.settings_paths):
        data = _load(path)
        if data is None:
            continue
        _, migration = migrate_legacy_namespace(data)
        findings.extend(_rule_finding(path=path, move=move) for move in migration.rule_moves)
        if migration.plugin_id_move is not None:
            findings.append(_plugin_id_finding(path=path, pruned=migration.plugin_id_move.pruned))
    return findings


def remediate(finding: Finding) -> Remediation:
    """Propose the rewrite (or prune) for one legacy spelling."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Flag permission rules and enabledPlugins ids still spelled for the "
        "pre-rename `Dev10x` plugin. They match nothing, so a stale deny or "
        "ask guards nothing (GH-1501)."
    ),
    detect=detect,
    remediate=remediate,
)
