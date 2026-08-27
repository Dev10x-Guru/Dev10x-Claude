"""Tracker-keyed permission seeding (GH-768).

``ensure-base`` used to seed the Linear MCP rules unconditionally, so a
Jira or GitHub-Issues user collected ~35 inert `mcp__claude_ai_Linear__*`
allows and ~5 inert denies while their own tracker's tools still
prompted on first use.

This module keeps the tracker→rules mapping in the shipped catalog —
under `tracker_permissions:` / `tracker_denies:`, keyed by tracker name
— and folds only the selected tracker's block into the flat
`base_permissions` / `base_denies` lists that
:func:`~dev10x.domain.common.policy_migration.migrate_flat_config`
consumes. Selecting is therefore a pure transformation over the config
dict, applied before migration, and needs no change to the Policy
pipeline downstream.

The interim home is the flat catalog rather than a bespoke new file:
when PAP-2 lands a structured Policy catalog, a `tracker:` key on
catalog groups replaces this block and :func:`apply_tracker_selection`
becomes a filter over policies instead of over YAML.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

ALLOW_KEY = "base_permissions"
DENY_KEY = "base_denies"
TRACKER_ALLOW_KEY = "tracker_permissions"
TRACKER_DENY_KEY = "tracker_denies"


class Tracker(StrEnum):
    """Issue trackers with a first-class permission block (v1 scope).

    GitLab and ClickUp are deliberately absent: ClickUp has no native
    skill or MCP path at all, and GitLab's `glab` surface has not been
    curated. Both are tracked as follow-ups rather than shipped as
    empty blocks that would look supported.
    """

    LINEAR = "linear"
    JIRA = "jira"
    GITHUB = "github"

    @classmethod
    def default(cls) -> Tracker:
        """Linear — the historical unconditional behaviour (GH-204)."""
        return cls.LINEAR


@dataclass(frozen=True)
class TrackerRules:
    """The allow/deny rules one tracker contributes to the baseline."""

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.allow or self.deny)


def parse_tracker(value: object) -> Tracker | None:
    """Coerce a config value to a :class:`Tracker`, or ``None``.

    ``None`` means "not configured" — distinct from an unrecognised
    name, which also returns ``None`` so a typo degrades to the
    caller's default rather than raising inside a seeding run.
    """
    if not isinstance(value, str):
        return None
    try:
        return Tracker(value.strip().lower())
    except ValueError:
        return None


def _rules_for(*, config: dict, tracker: Tracker) -> TrackerRules:
    def entries(key: str) -> tuple[str, ...]:
        block = config.get(key)
        if not isinstance(block, dict):
            return ()
        rules = block.get(tracker.value)
        if not isinstance(rules, list):
            return ()
        return tuple(rule for rule in rules if isinstance(rule, str))

    return TrackerRules(allow=entries(TRACKER_ALLOW_KEY), deny=entries(TRACKER_DENY_KEY))


def tracker_inventory(*, config: dict) -> dict[Tracker, TrackerRules]:
    """Every tracker block the catalog defines, keyed by tracker."""
    return {tracker: _rules_for(config=config, tracker=tracker) for tracker in Tracker}


def apply_tracker_selection(*, config: dict, tracker: Tracker) -> dict:
    """Return ``config`` with only ``tracker``'s rules folded into the flat lists.

    The input is not mutated — seeding runs read the shipped catalog
    from a cached loader, so mutating it would leak the first run's
    tracker into every later one in the same process.

    Rules already present in the flat list are not duplicated, which
    keeps the function idempotent: applying the same selection twice
    yields the same config.
    """
    rules = _rules_for(config=config, tracker=tracker)
    merged = dict(config)
    for key, additions in ((ALLOW_KEY, rules.allow), (DENY_KEY, rules.deny)):
        existing = [rule for rule in merged.get(key, []) if isinstance(rule, str)]
        merged[key] = existing + [rule for rule in additions if rule not in existing]
    return merged


def prunable_rules(*, config: dict, tracker: Tracker) -> tuple[str, ...]:
    """Rules belonging to every tracker OTHER than the selected one.

    The inputs to the issue's optional "offer to prune the unused
    tracker's rules" step. A rule the selected tracker also claims is
    excluded, so a shared tool name is never proposed for removal.
    """
    keep = set(_rules_for(config=config, tracker=tracker).allow)
    keep.update(_rules_for(config=config, tracker=tracker).deny)
    inventory = tracker_inventory(config=config)
    prunable: list[str] = []
    for other, rules in inventory.items():
        if other is tracker:
            continue
        prunable.extend(rule for rule in (*rules.allow, *rules.deny) if rule not in keep)
    return tuple(dict.fromkeys(prunable))


__all__ = [
    "ALLOW_KEY",
    "DENY_KEY",
    "TRACKER_ALLOW_KEY",
    "TRACKER_DENY_KEY",
    "Tracker",
    "TrackerRules",
    "apply_tracker_selection",
    "parse_tracker",
    "prunable_rules",
    "tracker_inventory",
]
