"""Three-way catalog merge for permission base rules (GH-912, ADR-0021).

The userspace catalog (``~/.config/Dev10x/projects.yaml``) used to
*shadow* the shipped one: ``resolve_config`` returned the first existing
candidate, so a userspace file created once by ``permission init`` hid
every safe default shipped afterwards, while ``ensure-base`` validated
against the stale copy and reported success.

This module replaces that selection with a merge::

    effective = shipped ⊕ user_additions ⊖ user_suppressions

Only ``base_permissions`` and ``base_denies`` merge. Machine-specific
keys (``roots``, ``workspace_directories``, ``include_user_settings``)
stay user-owned and are read from the userspace catalog alone —
see ADR-0021 rule 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

ALLOW_KEY = "base_permissions"
DENY_KEY = "base_denies"
SUPPRESS_KEY = "base_permission_suppressions"


@dataclass(frozen=True)
class CatalogDrift:
    """The three-way split between a shipped catalog and a user copy.

    ``missing_from_user`` is the column that matters: those entries are
    blessed upstream yet absent downstream, so the user pays a prompt
    per tool per project for rules they already have.
    """

    missing_from_user: tuple[str, ...] = ()
    user_only: tuple[str, ...] = ()
    suppressed: tuple[str, ...] = ()
    denies_missing_from_user: tuple[str, ...] = ()
    denies_user_only: tuple[str, ...] = ()
    ignored_deny_suppressions: tuple[str, ...] = ()

    @property
    def has_missing_defaults(self) -> bool:
        return bool(self.missing_from_user or self.denies_missing_from_user)

    @property
    def is_clean(self) -> bool:
        return not (
            self.missing_from_user
            or self.user_only
            or self.suppressed
            or self.denies_missing_from_user
            or self.denies_user_only
            or self.ignored_deny_suppressions
        )


@dataclass(frozen=True)
class MergedCatalog:
    """The effective catalog plus the drift that produced it."""

    config: dict = field(default_factory=dict)
    drift: CatalogDrift = field(default_factory=CatalogDrift)


def _rules(config: dict | None, key: str) -> list[str]:
    """Read a rule list defensively.

    A malformed or absent key contributes nothing rather than raising —
    a partially-written catalog must not take down every ``permission``
    subcommand.
    """
    if not isinstance(config, dict):
        return []
    value = config.get(key)
    if not isinstance(value, list):
        return []
    return [rule for rule in value if isinstance(rule, str)]


def _ordered_union(base: list[str], additions: list[str]) -> list[str]:
    """Concatenate preserving shipped order, then user order, no dupes."""
    seen = set(base)
    merged = list(base)
    for rule in additions:
        if rule not in seen:
            seen.add(rule)
            merged.append(rule)
    return merged


def compute_drift(*, shipped: dict | None, user: dict | None) -> CatalogDrift:
    """Classify every rule as shipped-only, user-only, or suppressed."""
    shipped_allow = _rules(shipped, ALLOW_KEY)
    user_allow = _rules(user, ALLOW_KEY)
    shipped_deny = _rules(shipped, DENY_KEY)
    user_deny = _rules(user, DENY_KEY)
    suppressions = _rules(user, SUPPRESS_KEY)

    shipped_allow_set = set(shipped_allow)
    user_allow_set = set(user_allow)
    shipped_deny_set = set(shipped_deny)
    user_deny_set = set(user_deny)
    suppressed_set = set(suppressions)

    # A suppression naming a shipped deny is refused, not honored:
    # denies are the safety floor (ADR-0021 rule 2, GH-925 E6).
    ignored_deny_suppressions = tuple(rule for rule in suppressions if rule in shipped_deny_set)

    return CatalogDrift(
        missing_from_user=tuple(
            rule
            for rule in shipped_allow
            if rule not in user_allow_set and rule not in suppressed_set
        ),
        user_only=tuple(rule for rule in user_allow if rule not in shipped_allow_set),
        suppressed=tuple(rule for rule in suppressions if rule not in shipped_deny_set),
        denies_missing_from_user=tuple(rule for rule in shipped_deny if rule not in user_deny_set),
        denies_user_only=tuple(rule for rule in user_deny if rule not in shipped_deny_set),
        ignored_deny_suppressions=ignored_deny_suppressions,
    )


def merge_catalogs(*, shipped: dict | None, user: dict | None) -> MergedCatalog:
    """Merge shipped defaults into a user catalog (ADR-0021).

    The returned config is the user's catalog with its ``base_permissions``
    and ``base_denies`` replaced by the merged sets. Every other key is
    passed through untouched, so machine-specific settings keep the
    user's values and a caller that only reads ``roots`` sees no change.

    Passing ``user=None`` (no userspace catalog yet) yields the shipped
    catalog unchanged, which is the correct pre-``init`` behaviour.
    """
    if not isinstance(user, dict):
        return MergedCatalog(config=dict(shipped) if isinstance(shipped, dict) else {})
    if not isinstance(shipped, dict):
        return MergedCatalog(config=dict(user))

    drift = compute_drift(shipped=shipped, user=user)
    suppressed = set(drift.suppressed)

    merged_allow = [
        rule
        for rule in _ordered_union(_rules(shipped, ALLOW_KEY), _rules(user, ALLOW_KEY))
        if rule not in suppressed
    ]
    # Denies union unconditionally — suppressions never reach this list.
    merged_deny = _ordered_union(_rules(shipped, DENY_KEY), _rules(user, DENY_KEY))

    if drift.ignored_deny_suppressions:
        log.warning(
            "Refusing %d deny suppression(s); denies are the safety floor: %s",
            len(drift.ignored_deny_suppressions),
            ", ".join(drift.ignored_deny_suppressions),
        )

    config = dict(user)
    config[ALLOW_KEY] = merged_allow
    config[DENY_KEY] = merged_deny
    return MergedCatalog(config=config, drift=drift)


def format_drift_report(drift: CatalogDrift) -> list[str]:
    """Render the drift as user-facing lines (one concern per block)."""
    if drift.is_clean:
        return ["Catalog is in sync — no drift between shipped and userspace."]

    lines: list[str] = []

    def block(title: str, rules: tuple[str, ...]) -> None:
        if not rules:
            return
        lines.append(f"-- {title} ({len(rules)}) --")
        lines.extend(f"  {rule}" for rule in rules)
        lines.append("")

    block("shipped but MISSING from userspace", drift.missing_from_user)
    block("shipped DENIES missing from userspace", drift.denies_missing_from_user)
    block("userspace-only, not shipped", drift.user_only)
    block("userspace-only denies, not shipped", drift.denies_user_only)
    block("explicitly suppressed by the user", drift.suppressed)
    block(
        "REFUSED deny suppressions (denies are the safety floor)",
        drift.ignored_deny_suppressions,
    )

    while lines and lines[-1] == "":
        lines.pop()

    if drift.has_missing_defaults:
        lines.append(
            "Shipped defaults are missing downstream. They now merge in "
            "automatically (ADR-0021); previously they were invisible."
        )
    return lines
