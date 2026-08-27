"""Strategy: ask-shadows-allow (GH-1067).

An ``ask`` (or ``deny``) rule outranks a broader ``allow`` rule, so a
narrow gate silently carves a hole out of a family the catalog already
pre-approved. Nothing in the settings file shows the conflict: both
entries look correct in isolation, and only the prompt at 3 a.m. reveals
that one was overriding the other.

Evidence (GH-1007 E10/D10): a foreman cleanup command
``git branch -D <a> <b>`` hit a confirmation prompt because ask entries
for ``git branch -D`` / ``-d`` were shadowing three existing allow rules
(``git branch:*``, ``-d``, ``--delete``). Unattended, that prompt is a
silent wedge — no one is present to answer it.

The same shape explains the cross-scope split-brain in GH-1069 E2, where
a global ask on ``git stash drop`` shadowed the global ``git stash:*``
allow in every project but the one carrying a local override.

The strategy reports; the doctor's Phase 4 owns the write, and the user
picks which bucket the rule belongs in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)

_GATE_BUCKETS = ("ask", "deny")


@dataclass(frozen=True)
class ShadowedAllowRemediation:
    """Remediation payload for an ask-shadows-allow finding."""

    gate_bucket: str
    gate_rule: str
    shadowed_allow_rules: tuple[str, ...]
    settings_path: str

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=self.settings_path,
            action={
                "bucket": self.gate_bucket,
                "rule": self.gate_rule,
                "shadowed_allow_rules": list(self.shadowed_allow_rules),
                "reason": (
                    f"{self.gate_bucket!r} outranks 'allow', so this rule gates "
                    "commands the allow rules listed here already pre-approve. "
                    "Pick one bucket: keep the gate and narrow the allow rules, "
                    "or drop the gate and let the allow rules stand."
                ),
            },
        )


def _settings_paths_from_context(context: Context) -> list[Path]:
    paths = list(context.settings_paths)
    if not paths:
        home = Path.home()
        paths = [
            home / ".claude" / "settings.json",
            home / ".claude" / "settings.local.json",
        ]
    return paths


def _load_buckets(path: Path) -> dict[str, list[str]]:
    """Read ``permissions.{allow,ask,deny}`` from one settings file."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        return {}
    return {
        bucket: [rule for rule in permissions.get(bucket, []) if isinstance(rule, str)]
        for bucket in ("allow", *_GATE_BUCKETS)
        if isinstance(permissions.get(bucket), list)
    }


def _shadowed_by(*, gate: AllowRule, allows: list[AllowRule]) -> list[AllowRule]:
    """Allow rules whose coverage this gate rule overrides.

    An allow rule is shadowed when it would have matched the gate rule's
    own command shape — an exact duplicate across buckets, or a broader
    family the gate carves into.
    """
    value = gate.representative_value
    return [allow for allow in allows if allow.tool == gate.tool and allow.matches_prefix(value)]


def detect(context: Context) -> list[Finding]:
    """Report every ask/deny rule that overrides a same-family allow rule."""
    findings: list[Finding] = []
    for path in _settings_paths_from_context(context):
        buckets = _load_buckets(path)
        allows = [AllowRule.parse(raw) for raw in buckets.get("allow", [])]
        if not allows:
            continue
        for bucket in _GATE_BUCKETS:
            for raw in buckets.get(bucket, []):
                shadowed = _shadowed_by(gate=AllowRule.parse(raw), allows=allows)
                if not shadowed:
                    continue
                findings.append(_finding(bucket=bucket, raw=raw, shadowed=shadowed, path=path))
    return findings


def _finding(
    *,
    bucket: str,
    raw: str,
    shadowed: list[AllowRule],
    path: Path,
) -> Finding:
    shadowed_raws = tuple(allow.raw for allow in shadowed)
    listed = ", ".join(f"``{rule}``" for rule in shadowed_raws)
    return Finding(
        strategy_id="ask-shadows-allow",
        severity="drift",
        location=str(path),
        evidence=(
            f"rule ``{raw}`` in '{bucket}' shadows allow rule(s) {listed} — "
            f"'{bucket}' outranks 'allow', so those commands still prompt"
        ),
        proposed_fix=(
            "Pick a bucket. Keep the gate only if the narrower shape genuinely "
            "warrants a prompt, and narrow the allow rule(s) to match; otherwise "
            "drop the gate so the pre-approved family works unattended. A prompt "
            "no one is present to answer is a silent wedge, not a safeguard."
        ),
        data=ShadowedAllowRemediation(
            gate_bucket=bucket,
            gate_rule=raw,
            shadowed_allow_rules=shadowed_raws,
            settings_path=str(path),
        ),
    )


def remediate(finding: Finding) -> Remediation:
    """Propose reconciling the shadowed rule into a single bucket."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id="ask-shadows-allow",
    description=(
        "Surface ask/deny rules that outrank a same-family allow rule. The "
        "conflict is invisible in the settings file — both entries look "
        "correct alone — and shows up only as an unexpected prompt, which "
        "in an unattended run is a silent wedge (GH-1067, GH-1007 E10/D10)."
    ),
    detect=detect,
    remediate=remediate,
)
