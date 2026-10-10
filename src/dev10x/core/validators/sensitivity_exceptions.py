"""Loader for the user-owned sensitivity-exception catalog (GH-604).

Reads ``~/.config/Dev10x/sensitivity-exceptions.yaml`` (Tier 2, synced
across worktrees) into domain :class:`SensitivityException` value
objects. The matching logic itself is pure domain code
(:func:`dev10x.domain.sensitivity.resolve_exception_effect`); this
module owns only the file I/O and YAML→value-object translation, per
``.claude/rules/script-domain-boundaries.md``.

The loader is defensive: a missing file, malformed YAML, or an invalid
entry yields an empty/partial list with a logged warning rather than
raising — a broken catalog must never break the bash hook (fail open to
DX014's default ``ask`` elevation).
"""

from __future__ import annotations

import logging
import re

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.sensitivity import ExceptionEffect, SensitivityException, SensitivityLabel

log = logging.getLogger(__name__)


def load_sensitivity_exceptions() -> list[SensitivityException]:
    """Return catalog entries from the user config, or ``[]`` when absent."""
    path = Dev10xConfigDir.sensitivity_exceptions_yaml()
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read sensitivity-exception catalog %s: %s", path, exc)
        return []
    return _parse_entries(raw=raw, source=str(path))


def _parse_entries(*, raw: object, source: str) -> list[SensitivityException]:
    if not isinstance(raw, dict):
        log.warning("Sensitivity-exception catalog %s is not a mapping; ignoring", source)
        return []
    entries = raw.get("exceptions")
    if entries is None:
        return []
    if not isinstance(entries, list):
        log.warning("'exceptions' in %s must be a list; ignoring", source)
        return []
    parsed: list[SensitivityException] = []
    for index, entry in enumerate(entries):
        exception = _parse_entry(entry=entry, source=source, index=index)
        if exception is not None:
            parsed.append(exception)
    return parsed


def _parse_entry(*, entry: object, source: str, index: int) -> SensitivityException | None:
    if not isinstance(entry, dict):
        log.warning("Entry %d in %s is not a mapping; skipping", index, source)
        return None
    try:
        return SensitivityException(
            effect=_parse_effect(entry.get("effect")),
            label=_parse_label(entry.get("label")),
            shape=_compile(entry.get("shape")),
            target=_compile(entry.get("target")),
            description=str(entry.get("description", "")),
        )
    except (ValueError, re.error) as exc:
        log.warning("Skipping invalid sensitivity exception %d in %s: %s", index, source, exc)
        return None


def _parse_effect(value: object) -> ExceptionEffect:
    if value is None:
        return ExceptionEffect.ALLOW
    return ExceptionEffect(str(value).strip().lower())


def _parse_label(value: object) -> SensitivityLabel | None:
    if value is None:
        return None
    return SensitivityLabel(str(value).strip().lower())


def _compile(value: object) -> re.Pattern[str] | None:
    if value is None:
        return None
    return re.compile(str(value), re.IGNORECASE)
