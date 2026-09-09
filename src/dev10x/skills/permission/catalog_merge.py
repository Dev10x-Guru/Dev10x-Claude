"""Three-way catalog merge for permission base rules (GH-912, ADR-0021).

The userspace catalog (``~/.config/Dev10x/projects.yaml``) used to
*shadow* the shipped one: ``resolve_config`` returned the first existing
candidate, so a userspace file created once by ``permission init`` hid
every safe default shipped afterwards, while ``ensure-base`` validated
against the stale copy and reported success.

This module replaces that selection with a merge::

    effective = shipped ⊕ user_additions ⊖ user_suppressions

Every key carrying *shipped baseline content* merges. Machine-specific
keys (``roots``, ``workspace_directories``, ``include_user_settings``,
``plugin_cache``) stay user-owned and are read from the userspace
catalog alone — see ADR-0021 rule 3.

GH-1248/GH-1249: originally only ``base_permissions`` and
``base_denies`` merged, and every other key fell through an implicit
"pass through untouched" branch. That branch was correct for the
machine-specific keys it was written for, and silently wrong for
``base_asks`` (GH-1149) and ``tracker_permissions`` /
``tracker_denies`` (GH-768) when those shipped later: a catalog
created before them never received them, and nothing reported the
omission. On one observed machine that meant zero ``ask`` rules
reached any settings file, and a repo pinned ``tracker: github`` was
seeded with no github tracker rules at all.

The classification is now explicit rather than residual:
:data:`MERGED_LIST_KEYS`, :data:`MERGED_TRACKER_KEYS` and
:data:`USER_OWNED_KEYS` name every key, and
:func:`unclassified_shipped_keys` warns about any shipped key in none
of them — so the next key added to the shipped catalog cannot repeat
this by omission.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

ALLOW_KEY = "base_permissions"
DENY_KEY = "base_denies"
ASK_KEY = "base_asks"
SUPPRESS_KEY = "base_permission_suppressions"

TRACKER_ALLOW_KEY = "tracker_permissions"
TRACKER_DENY_KEY = "tracker_denies"

#: Flat rule lists that merge shipped ⊕ user.
MERGED_LIST_KEYS = (ALLOW_KEY, DENY_KEY, ASK_KEY)

#: Tracker-keyed dicts of rule lists that merge per tracker.
MERGED_TRACKER_KEYS = (TRACKER_ALLOW_KEY, TRACKER_DENY_KEY)

#: Machine-specific keys read from the userspace catalog alone.
USER_OWNED_KEYS = (
    "roots",
    "workspace_directories",
    "include_user_settings",
    "plugin_cache",
)

#: Keys where a user suppression is refused — these are the safety
#: floor and a downstream catalog must not opt out of them.
SUPPRESSION_REFUSED_KEYS = (DENY_KEY, TRACKER_DENY_KEY)


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
    asks_missing_from_user: tuple[str, ...] = ()
    asks_user_only: tuple[str, ...] = ()
    #: Tracker rules blessed upstream but absent downstream, keyed by
    #: tracker name (``linear`` / ``jira`` / ``github``).
    tracker_missing_from_user: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tracker_denies_missing_from_user: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Shipped sections wholly absent downstream. Distinct from
    #: per-rule drift: a missing *section* means a whole capability
    #: never arrived, which reads as "0 missing" to any check that
    #: only compares rules the user's catalog already declares.
    missing_sections: tuple[str, ...] = ()
    #: Shipped keys in neither the merge set nor USER_OWNED_KEYS.
    unclassified_keys: tuple[str, ...] = ()

    @property
    def has_missing_defaults(self) -> bool:
        return bool(
            self.missing_from_user
            or self.denies_missing_from_user
            or self.asks_missing_from_user
            or self.tracker_missing_from_user
            or self.tracker_denies_missing_from_user
            or self.missing_sections
        )

    @property
    def is_clean(self) -> bool:
        return not (
            self.missing_from_user
            or self.user_only
            or self.suppressed
            or self.denies_missing_from_user
            or self.denies_user_only
            or self.ignored_deny_suppressions
            or self.asks_missing_from_user
            or self.asks_user_only
            or self.tracker_missing_from_user
            or self.tracker_denies_missing_from_user
            or self.missing_sections
            or self.unclassified_keys
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


def _tracker_rules(config: dict | None, key: str) -> dict[str, list[str]]:
    """Read a tracker-keyed mapping of rule lists defensively.

    Shaped ``{"linear": [...], "jira": [...], "github": [...]}``. Same
    contract as :func:`_rules`: anything malformed contributes nothing
    rather than raising.
    """
    if not isinstance(config, dict):
        return {}
    value = config.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        tracker: [rule for rule in rules if isinstance(rule, str)]
        for tracker, rules in value.items()
        if isinstance(tracker, str) and isinstance(rules, list)
    }


def _merge_tracker_rules(
    *,
    shipped: dict[str, list[str]],
    user: dict[str, list[str]],
    suppressed: set[str],
) -> dict[str, list[str]]:
    """Union shipped and user rules per tracker key.

    A tracker present in only one side is carried through whole: a user
    who added a tracker the plugin does not ship keeps it, and a tracker
    shipped after their catalog was written arrives.
    """
    merged: dict[str, list[str]] = {}
    for tracker in [*shipped, *(t for t in user if t not in shipped)]:
        rules = _ordered_union(shipped.get(tracker, []), user.get(tracker, []))
        merged[tracker] = [rule for rule in rules if rule not in suppressed]
    return merged


def _tracker_drift(
    *, shipped: dict[str, list[str]], user: dict[str, list[str]]
) -> dict[str, tuple[str, ...]]:
    """Per-tracker rules blessed upstream but absent downstream."""
    drift: dict[str, tuple[str, ...]] = {}
    for tracker, shipped_rules in shipped.items():
        user_rules = set(user.get(tracker, []))
        missing = tuple(rule for rule in shipped_rules if rule not in user_rules)
        if missing:
            drift[tracker] = missing
    return drift


def unclassified_shipped_keys(shipped: dict | None) -> tuple[str, ...]:
    """Shipped keys in neither the merge set nor :data:`USER_OWNED_KEYS`.

    A key that is neither merged nor explicitly user-owned is the shape
    of the GH-1249 defect: it passes through from the user's catalog, so
    a catalog written before the key existed never receives it and
    nothing says so. Naming the residue turns that silence into a
    warning at the next catalog read.
    """
    if not isinstance(shipped, dict):
        return ()
    classified = {*MERGED_LIST_KEYS, *MERGED_TRACKER_KEYS, *USER_OWNED_KEYS, SUPPRESS_KEY}
    return tuple(key for key in shipped if key not in classified)


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

    shipped_ask = _rules(shipped, ASK_KEY)
    user_ask = _rules(user, ASK_KEY)
    shipped_ask_set = set(shipped_ask)
    user_ask_set = set(user_ask)

    shipped_tracker_allow = _tracker_rules(shipped, TRACKER_ALLOW_KEY)
    user_tracker_allow = _tracker_rules(user, TRACKER_ALLOW_KEY)
    shipped_tracker_deny = _tracker_rules(shipped, TRACKER_DENY_KEY)
    user_tracker_deny = _tracker_rules(user, TRACKER_DENY_KEY)

    # A suppression naming a shipped deny is refused, not honored:
    # denies are the safety floor (ADR-0021 rule 2, GH-925 E6). Tracker
    # denies are the same floor, so they are refused alongside.
    shipped_tracker_deny_set = {rule for rules in shipped_tracker_deny.values() for rule in rules}
    refused = shipped_deny_set | shipped_tracker_deny_set
    ignored_deny_suppressions = tuple(rule for rule in suppressions if rule in refused)

    return CatalogDrift(
        missing_from_user=tuple(
            rule
            for rule in shipped_allow
            if rule not in user_allow_set and rule not in suppressed_set
        ),
        user_only=tuple(rule for rule in user_allow if rule not in shipped_allow_set),
        suppressed=tuple(rule for rule in suppressions if rule not in refused),
        denies_missing_from_user=tuple(rule for rule in shipped_deny if rule not in user_deny_set),
        denies_user_only=tuple(rule for rule in user_deny if rule not in shipped_deny_set),
        ignored_deny_suppressions=ignored_deny_suppressions,
        asks_missing_from_user=tuple(
            rule for rule in shipped_ask if rule not in user_ask_set and rule not in suppressed_set
        ),
        asks_user_only=tuple(rule for rule in user_ask if rule not in shipped_ask_set),
        tracker_missing_from_user=_tracker_drift(
            shipped=shipped_tracker_allow, user=user_tracker_allow
        ),
        tracker_denies_missing_from_user=_tracker_drift(
            shipped=shipped_tracker_deny, user=user_tracker_deny
        ),
        missing_sections=_missing_sections(shipped=shipped, user=user),
        unclassified_keys=unclassified_shipped_keys(shipped),
    )


def _missing_sections(*, shipped: dict | None, user: dict | None) -> tuple[str, ...]:
    """Shipped merge-set sections wholly absent from the user catalog.

    Reported separately from per-rule drift because the two mean
    different things to a reader: per-rule drift says "you are behind by
    N rules", a missing section says "this capability never arrived at
    all". The second is what GH-1249 observed — a catalog with no
    ``tracker_permissions`` key looked clean to every rule-level check.
    """
    if not isinstance(shipped, dict) or not isinstance(user, dict):
        return ()
    return tuple(
        key
        for key in (*MERGED_LIST_KEYS, *MERGED_TRACKER_KEYS)
        if key in shipped and key not in user
    )


def merge_catalogs(*, shipped: dict | None, user: dict | None) -> MergedCatalog:
    """Merge shipped defaults into a user catalog (ADR-0021).

    The returned config is the user's catalog with every shipped-content
    key replaced by the merged set: the flat lists in
    :data:`MERGED_LIST_KEYS` and the tracker-keyed dicts in
    :data:`MERGED_TRACKER_KEYS`. The keys in :data:`USER_OWNED_KEYS` are
    passed through untouched, so machine-specific settings keep the
    user's values and a caller that only reads ``roots`` sees no change.

    Suppressions apply to the allow tiers (``base_permissions``,
    ``base_asks``) and are refused for the deny tiers — denies are the
    safety floor (ADR-0021 rule 2). ``base_asks`` accepts suppression
    because an ``ask`` is a prompt rather than a grant: a user who has
    decided a prompt is noise may silence it, which is not true of a
    deny.

    Passing ``user=None`` (no userspace catalog yet) yields the shipped
    catalog unchanged, which is the correct pre-``init`` behaviour.
    """
    if not isinstance(user, dict):
        return MergedCatalog(config=dict(shipped) if isinstance(shipped, dict) else {})
    if not isinstance(shipped, dict):
        return MergedCatalog(config=dict(user))

    drift = compute_drift(shipped=shipped, user=user)
    suppressed = set(drift.suppressed)

    config = dict(user)

    # Allow tiers honour suppressions; deny tiers union unconditionally.
    for key in MERGED_LIST_KEYS:
        merged = _ordered_union(_rules(shipped, key), _rules(user, key))
        if key not in SUPPRESSION_REFUSED_KEYS:
            merged = [rule for rule in merged if rule not in suppressed]
        config[key] = merged

    for key in MERGED_TRACKER_KEYS:
        config[key] = _merge_tracker_rules(
            shipped=_tracker_rules(shipped, key),
            user=_tracker_rules(user, key),
            suppressed=set() if key in SUPPRESSION_REFUSED_KEYS else suppressed,
        )

    if drift.ignored_deny_suppressions:
        log.warning(
            "Refusing %d deny suppression(s); denies are the safety floor: %s",
            len(drift.ignored_deny_suppressions),
            ", ".join(drift.ignored_deny_suppressions),
        )

    if drift.unclassified_keys:
        log.warning(
            "Shipped catalog key(s) neither merged nor user-owned, so a user "
            "catalog predating them never receives them (GH-1249): %s",
            ", ".join(drift.unclassified_keys),
        )

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

    # Whole-section gaps lead: a missing section means a capability
    # never arrived, which every rule-level block below would report as
    # clean (GH-1249).
    if drift.missing_sections:
        lines.append(
            f"-- shipped SECTIONS absent from userspace ({len(drift.missing_sections)}) --"
        )
        lines.extend(f"  {key}" for key in drift.missing_sections)
        lines.append("  These merge in automatically now; before GH-1249 they did not.")
        lines.append("")

    block("shipped but MISSING from userspace", drift.missing_from_user)
    block("shipped ASKS missing from userspace", drift.asks_missing_from_user)
    block("shipped DENIES missing from userspace", drift.denies_missing_from_user)

    def tracker_block(title: str, drifted: dict[str, tuple[str, ...]]) -> None:
        if not drifted:
            return
        total = sum(len(rules) for rules in drifted.values())
        lines.append(f"-- {title} ({total}) --")
        for tracker, rules in drifted.items():
            lines.append(f"  [{tracker}]")
            lines.extend(f"    {rule}" for rule in rules)
        lines.append("")

    tracker_block("shipped TRACKER rules missing from userspace", drift.tracker_missing_from_user)
    tracker_block(
        "shipped TRACKER denies missing from userspace",
        drift.tracker_denies_missing_from_user,
    )

    block("userspace-only, not shipped", drift.user_only)
    block("userspace-only asks, not shipped", drift.asks_user_only)
    block("userspace-only denies, not shipped", drift.denies_user_only)
    block("explicitly suppressed by the user", drift.suppressed)
    block(
        "REFUSED deny suppressions (denies are the safety floor)",
        drift.ignored_deny_suppressions,
    )
    block(
        "shipped keys neither merged nor user-owned (report upstream)",
        drift.unclassified_keys,
    )

    while lines and lines[-1] == "":
        lines.pop()

    if drift.has_missing_defaults:
        lines.append(
            "Shipped defaults are missing downstream. They now merge in "
            "automatically (ADR-0021); previously they were invisible."
        )
    return lines
