"""Strategy: extracted-skill-rules (GH-1571, ADR-0034 Stage B).

Each Stage B step moves a skill from ``dev10x:<skill>`` to
``dev10x-<key>:<skill>``. upgrade-cleanup migrates the user's Dev10x
config files, but a permission rule a person wrote by hand, such as
``Skill(dev10x:park)``, still names the old invocation and matches
nothing. On an allow rule that costs a prompt; on a deny or ask rule it
is a guardrail that reads as present and guards nothing, which is why
those are ``critical``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.core.plugin_map import CORE_PLUGIN_NAME, PluginMap, load_plugin_map
from dev10x.core.skills.doctor.strategy import Context, Finding, Remediation, Severity, Strategy

STRATEGY_ID = "extracted-skill-rules"

_PERMISSION_LISTS = ("deny", "ask", "allow")
_GUARDRAIL_LISTS = frozenset({"deny", "ask"})
_SKILL_RULE = re.compile(
    rf"^Skill\({re.escape(CORE_PLUGIN_NAME)}:(?P<skill>[a-z0-9][a-z0-9-]*)(?P<rest>[^)]*)\)$"
)


@dataclass(frozen=True)
class ExtractedSkillRuleRemediation:
    """Remediation payload: one rule to rewrite to the satellite's name."""

    settings_path: str
    list_name: str
    rule: str
    replacement: str
    pruned: bool

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=f"permissions.{self.list_name}",
            action={
                "path": self.settings_path,
                "operation": "prune" if self.pruned else "rewrite",
                "rule": self.rule,
                "replacement": self.replacement,
            },
        )


def _permissions(*, path: Path) -> dict[str, list[str]]:
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    permissions = document.get("permissions") if isinstance(document, dict) else None
    if not isinstance(permissions, dict):
        return {}
    return {
        name: [rule for rule in permissions.get(name) or [] if isinstance(rule, str)]
        for name in _PERMISSION_LISTS
        if isinstance(permissions.get(name), list)
    }


def replacement_for(*, rule: str, plugin_map: PluginMap) -> str | None:
    """The satellite spelling of a ``Skill(dev10x:<skill>)`` rule, if it moved."""
    match = _SKILL_RULE.match(rule)
    if match is None:
        return None
    key = plugin_map.plugin_for(skill=match["skill"])
    if key is None or not plugin_map.is_extracted(key=key):
        return None
    name = plugin_map.installed_name(key=key)
    return f"Skill({name}:{match['skill']}{match['rest']})"


def _finding(
    *,
    path: Path,
    list_name: str,
    rule: str,
    replacement: str,
    pruned: bool,
) -> Finding:
    guardrail = list_name in _GUARDRAIL_LISTS
    severity: Severity = "critical" if guardrail and not pruned else "drift"
    consequence = "guards nothing" if guardrail else "grants nothing"
    if pruned:
        consequence = f"is a stale duplicate: ``{replacement}`` is already in the list"
    return Finding(
        strategy_id=STRATEGY_ID,
        severity=severity,
        location=f"{path}:permissions.{list_name}",
        evidence=(
            f"``{rule}`` names a skill that moved to its own plugin; this "
            f"{list_name} rule {consequence}."
        ),
        proposed_fix=f"Remove ``{rule}``." if pruned else f"Rewrite to ``{replacement}``.",
        data=ExtractedSkillRuleRemediation(
            settings_path=str(path),
            list_name=list_name,
            rule=rule,
            replacement=replacement,
            pruned=pruned,
        ),
    )


def detect_with_map(context: Context, *, plugin_map: PluginMap) -> list[Finding]:
    """Report every ``Skill(dev10x:<skill>)`` rule whose skill was extracted."""
    findings: list[Finding] = []
    for path in dict.fromkeys(context.settings_paths):
        for list_name, rules in _permissions(path=path).items():
            for rule in rules:
                replacement = replacement_for(rule=rule, plugin_map=plugin_map)
                if replacement is None:
                    continue
                findings.append(
                    _finding(
                        path=path,
                        list_name=list_name,
                        rule=rule,
                        replacement=replacement,
                        pruned=replacement in rules,
                    )
                )
    return findings


def detect(context: Context) -> list[Finding]:
    """Report stale core-namespace rules for skills ``plugins.yaml`` marks extracted."""
    return detect_with_map(context, plugin_map=load_plugin_map())


def remediate(finding: Finding) -> Remediation:
    """Propose rewriting the rule to the satellite's invocation name."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Flag `Skill(dev10x:<skill>)` permission rules for skills that moved "
        "to a satellite plugin. They match nothing, so a stale deny or ask "
        "guards nothing (GH-1571)."
    ),
    detect=detect,
    remediate=remediate,
)
