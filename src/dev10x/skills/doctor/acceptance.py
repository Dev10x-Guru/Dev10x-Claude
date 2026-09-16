"""Loader for the user-owned plugin-doctor acceptance catalog (GH-1321).

Reads ``~/.config/Dev10x/doctor-accepted-findings.yaml`` (Tier 2, so one
answer covers every project and worktree) and merges it with the shipped
defaults in :mod:`dev10x.domain.common.doctor_acceptance`. Matching is
pure domain code; this module owns only file I/O and YAML→value-object
translation, per ``.claude/rules/script-domain-boundaries.md``.

Catalog shape::

    accepted:
      - strategy: ask-shadows-allow
        location: "*/settings.local.json"   # optional glob; omit for "any"
        rationale: "narrow denies under broad allows are deliberate here"

``rationale`` is **required**, and an entry without one is rejected at
load rather than defaulted. The same choice the sensitivity-exception
catalog makes for its matchers (GH-604), for the same reason: an
unexplained suppression is indistinguishable from a forgotten one six
months later, and a catalog nobody can audit is how a baseline stops
being a ratchet and becomes a place findings go to disappear.

The loader is otherwise defensive: a missing file, malformed YAML, or an
invalid entry yields the shipped defaults with a logged warning rather
than raising — a broken overlay must never break ``dev10x doctor run``.
"""

from __future__ import annotations

import logging

import yaml

from dev10x.domain.common.doctor_acceptance import (
    ANY_LOCATION,
    DEFAULT_ACCEPTED_DOCTOR_FINDINGS,
    AcceptedDoctorFinding,
)
from dev10x.domain.dev10x_paths import Dev10xConfigDir

log = logging.getLogger(__name__)


def load_doctor_acceptances() -> tuple[AcceptedDoctorFinding, ...]:
    """User overlay entries first, then the shipped defaults."""
    path = Dev10xConfigDir.doctor_accepted_findings_yaml()
    if not path.exists():
        return DEFAULT_ACCEPTED_DOCTOR_FINDINGS
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read doctor acceptance catalog %s: %s", path, exc)
        return DEFAULT_ACCEPTED_DOCTOR_FINDINGS
    if not isinstance(raw, dict):
        log.warning("Doctor acceptance catalog %s is not a mapping; ignoring", path)
        return DEFAULT_ACCEPTED_DOCTOR_FINDINGS
    user = _parse_accepted(raw=raw.get("accepted"), source=str(path))
    return (*user, *DEFAULT_ACCEPTED_DOCTOR_FINDINGS)


def _parse_accepted(*, raw: object, source: str) -> tuple[AcceptedDoctorFinding, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        log.warning("'accepted' in %s must be a list; ignoring", source)
        return ()
    parsed = (_parse_entry(entry=entry, source=source, index=i) for i, entry in enumerate(raw))
    return tuple(entry for entry in parsed if entry is not None)


def _parse_entry(*, entry: object, source: str, index: int) -> AcceptedDoctorFinding | None:
    if not isinstance(entry, dict):
        log.warning("Acceptance entry %d in %s is not a mapping; skipping", index, source)
        return None
    strategy = entry.get("strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        log.warning("Acceptance entry %d in %s has no 'strategy'; skipping", index, source)
        return None
    rationale = entry.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        log.warning(
            "Acceptance entry %d in %s has no 'rationale'; skipping — an "
            "unexplained suppression cannot be audited later",
            index,
            source,
        )
        return None
    location = entry.get("location")
    return AcceptedDoctorFinding(
        strategy=strategy.strip(),
        rationale=rationale.strip(),
        location=location.strip()
        if isinstance(location, str) and location.strip()
        else ANY_LOCATION,
        source=source,
    )


__all__ = ["load_doctor_acceptances"]
