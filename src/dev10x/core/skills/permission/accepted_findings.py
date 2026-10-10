"""Loader for the user-owned accepted-findings catalog (GH-1053).

Reads ``~/.config/Dev10x/accepted-findings.yaml`` (Tier 2, so one answer
covers every project and worktree) and merges it with the shipped
defaults in :mod:`dev10x.domain.common.accepted_findings`. Matching is
pure domain code; this module owns only file I/O and YAML→value-object
translation, per ``.claude/rules/script-domain-boundaries.md``.

Catalog shape::

    accepted:
      - rule: "Bash(git clean -fd:*)"
        classifications: [REDUNDANT]     # optional; omit for "any finding"
        rationale: "scratch worktrees only"
    rejected:
      - "Bash(git push -f:*)"            # re-open a shipped acceptance

The loader is defensive: a missing file, malformed YAML, or an invalid
entry yields the shipped defaults with a logged warning rather than
raising — a broken overlay must never break ``dev10x permission audit``.
"""

from __future__ import annotations

import logging

import yaml

from dev10x.domain.common.accepted_findings import (
    DEFAULT_ACCEPTED_FINDINGS,
    AcceptedFinding,
)
from dev10x.domain.dev10x_paths import Dev10xConfigDir

log = logging.getLogger(__name__)


def load_accepted_findings() -> tuple[AcceptedFinding, ...]:
    """User overlay entries first, then the shipped defaults it kept.

    User entries lead so a restated rationale wins over the shipped one
    for the same rule (:func:`find_acceptance` takes the first match).
    """
    path = Dev10xConfigDir.accepted_findings_yaml()
    if not path.exists():
        return DEFAULT_ACCEPTED_FINDINGS
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read accepted-findings catalog %s: %s", path, exc)
        return DEFAULT_ACCEPTED_FINDINGS
    if not isinstance(raw, dict):
        log.warning("Accepted-findings catalog %s is not a mapping; ignoring", path)
        return DEFAULT_ACCEPTED_FINDINGS
    user = _parse_accepted(raw=raw.get("accepted"), source=str(path))
    rejected = _parse_rejected(raw=raw.get("rejected"), source=str(path))
    shipped = tuple(entry for entry in DEFAULT_ACCEPTED_FINDINGS if entry.rule not in rejected)
    return (*user, *shipped)


def _parse_accepted(*, raw: object, source: str) -> tuple[AcceptedFinding, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        log.warning("'accepted' in %s must be a list; ignoring", source)
        return ()
    parsed: list[AcceptedFinding] = []
    for index, entry in enumerate(raw):
        finding = _parse_entry(entry=entry, source=source, index=index)
        if finding is not None:
            parsed.append(finding)
    return tuple(parsed)


def _parse_entry(*, entry: object, source: str, index: int) -> AcceptedFinding | None:
    if not isinstance(entry, dict):
        log.warning("Accepted entry %d in %s is not a mapping; skipping", index, source)
        return None
    rule = entry.get("rule")
    if not isinstance(rule, str) or not rule.strip():
        log.warning("Accepted entry %d in %s has no 'rule'; skipping", index, source)
        return None
    return AcceptedFinding(
        rule=rule.strip(),
        rationale=str(entry.get("rationale", "accepted by the user")),
        classifications=_parse_classifications(entry.get("classifications")),
        source=source,
    )


def _parse_classifications(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value.strip().upper()})
    if isinstance(value, list):
        return frozenset(str(item).strip().upper() for item in value)
    return frozenset()


def _parse_rejected(*, raw: object, source: str) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        log.warning("'rejected' in %s must be a list; ignoring", source)
        return frozenset()
    return frozenset(str(item).strip() for item in raw)


__all__ = ["load_accepted_findings"]
