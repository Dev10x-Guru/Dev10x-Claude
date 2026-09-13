"""Strategy: retired-session-yaml (GH-1259).

ADR-0018 D2 moved durable posture to the global `friction.yaml` and
retired the per-repo `.claude/Dev10x/session.yaml`. Nothing was made
responsible for removing what was already there, and the migrator
deliberately will not: folding a stale file over live config would
overwrite the posture in force, so a repo already covered by a
`projects[]` entry reports `already-covered` and the leftover stays.

A leftover is inert only while that entry shadows it. Rename the repo
directory, drop the entry, or open a worktree the globs do not match,
and the file becomes the tier-2 read — at which point its residual v1
keys trip the `legacy_policy_keys` refusal and gate resolution stops.
The observed instance also asserted the *inverse* posture of the one in
force, so the trap is not merely a refusal but a contradiction.

The doctor is the right reporter: this is drift a supervisor cannot see
by reading either file alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.gate_policy import legacy_policy_keys
from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)

STRATEGY_ID = "retired-session-yaml"

#: Retired by ADR-0018 D2, relative to a checkout's `.claude/`.
_RETIRED_RELATIVE_PATH = Path("Dev10x") / "session.yaml"


@dataclass(frozen=True)
class RetiredSessionYamlRemediation:
    """Remediation payload for a leftover retired-path session file."""

    session_path: str
    legacy_keys: tuple[str, ...]

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="delegate_skill",
            target="Dev10x:plugin-maintenance",
            action={
                "operation": "remove-retired-session-yaml",
                "path": self.session_path,
                "legacy_keys": list(self.legacy_keys),
                "reason": (
                    "ADR-0018 D2 retired this path. The file is shadowed while a "
                    "friction.yaml projects[] entry matches this checkout, and "
                    "becomes the tier-2 read the moment that entry stops matching "
                    "— a renamed directory, a dropped entry, or a worktree the "
                    "globs miss. Delete it; the migrator will not, because folding "
                    "a stale file over live config would overwrite the posture in "
                    "force."
                ),
            },
        )


def _candidate_paths(context: Context) -> list[Path]:
    """Retired-path files reachable from the settings files we know about.

    `Context` carries no repo roots, but every project settings path is
    `<repo>/.claude/settings*.json`, so its parent is the `.claude/` the
    retired file would sit under.
    """
    seen: dict[Path, None] = {}
    for settings_path in context.settings_paths:
        candidate = settings_path.parent / _RETIRED_RELATIVE_PATH
        seen.setdefault(candidate, None)
    return list(seen)


def _loaded(path: Path) -> tuple[dict[str, Any], bool]:
    """The file's prefs, and whether they could be read at all.

    The second element is what keeps a parse failure from being graded as
    the mildest finding. An unreadable file yields no keys, and "no keys"
    is otherwise the evidence for "harmless, shadowed by the global
    friction.yaml" — so swallowing the error would report a file nobody
    could parse as the least urgent kind of leftover.
    """
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}, False
    return (parsed, True) if isinstance(parsed, dict) else ({}, False)


def _legacy_keys(prefs: dict[str, Any]) -> tuple[str, ...]:
    """Which v1 keys would make a tier-2 read of this file refuse."""
    active_modes = prefs.get("active_modes")
    gate_overlays = prefs.get("gate_overlays")
    gate_preset = prefs.get("gate_preset")
    return tuple(
        legacy_policy_keys(
            friction_level=prefs.get("friction_level"),
            walk_away=prefs.get("walk_away") is True,
            active_modes=active_modes if isinstance(active_modes, list) else [],
            gate_preset=gate_preset if isinstance(gate_preset, str) else None,
            gate_overlays=gate_overlays if isinstance(gate_overlays, list) else [],
        )
    )


def detect(context: Context) -> list[Finding]:
    """Report a retired-path `session.yaml` left behind by ADR-0018."""
    findings: list[Finding] = []
    for path in _candidate_paths(context):
        if not path.is_file():
            continue
        prefs, readable = _loaded(path)
        findings.append(_finding(path=path, legacy_keys=_legacy_keys(prefs), readable=readable))
    return findings


def _finding(*, path: Path, legacy_keys: tuple[str, ...], readable: bool) -> Finding:
    # Severity tracks consequence, not tidiness: a file carrying v1 keys
    # does not merely linger, it refuses gate resolution the moment it
    # stops being shadowed. A file nobody can parse is refused at least as
    # hard, so it is graded with them rather than as quiet drift.
    carries_legacy = bool(legacy_keys)
    named = ", ".join(legacy_keys)
    if not readable:
        detail = (
            ", and could not be parsed — a tier-2 read of it would fail "
            "outright, so it cannot be assumed harmless"
        )
    elif carries_legacy:
        detail = (
            f", and still declares posture through {named} — a tier-2 read "
            "of it would be refused, not translated"
        )
    else:
        detail = ", and is shadowed by the global friction.yaml"
    return Finding(
        strategy_id=STRATEGY_ID,
        severity="critical" if carries_legacy or not readable else "drift",
        location=str(path),
        evidence=f"``{path}`` sits on the path ADR-0018 D2 retired{detail}",
        proposed_fix=(
            "Delete the file. Durable posture lives in "
            "~/.config/Dev10x/friction.yaml; this copy is read only when no "
            "projects[] entry matches the checkout, which is exactly when its "
            "stale contents would take effect."
        ),
        data=RetiredSessionYamlRemediation(
            session_path=str(path),
            legacy_keys=legacy_keys,
        ),
    )


def remediate(finding: Finding) -> Remediation:
    """Propose removing the retired-path session file."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id=STRATEGY_ID,
    description=(
        "Flag a leftover .claude/Dev10x/session.yaml. ADR-0018 D2 retired the "
        "path and the migrator refuses to fold a file over live config, so the "
        "leftover survives — inert only while a friction.yaml entry shadows it, "
        "and a refusal or a contradiction the moment one stops (GH-1259)."
    ),
    detect=detect,
    remediate=remediate,
)
