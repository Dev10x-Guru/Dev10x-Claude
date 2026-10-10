"""IDE-keyed permission seeding (GH-1261).

The mirror of :mod:`dev10x.domain.common.tracker_choice`, for the same
reason it exists: an IDE MCP server is a property of *some* setups, so
seeding its rules unconditionally hands everyone else a pile of inert
allows — the failure GH-768 fixed for trackers.

``none`` is the resolved default rather than a named IDE, because unlike
a tracker (every project has one) most checkouts have no IDE server at
all. A user who pins nothing folds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dev10x.domain.common.tracker_choice import ALLOW_KEY, DENY_KEY

IDE_ALLOW_KEY = "ide_permissions"
IDE_DENY_KEY = "ide_denies"


class Ide(StrEnum):
    """IDE MCP servers with a first-class permission block (v1 scope).

    VS Code and the JetBrains siblings beyond PyCharm are absent
    deliberately: their tool surfaces have not been enumerated, and an
    empty block would look supported.
    """

    PYCHARM = "pycharm"
    NONE = "none"

    @classmethod
    def default(cls) -> Ide:
        return cls.NONE


@dataclass(frozen=True)
class IdeRules:
    """The allow/deny rules one IDE contributes to the baseline."""

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.allow or self.deny)


def parse_ide(value: object) -> Ide | None:
    """Coerce a config value to an :class:`Ide`, or ``None``.

    ``None`` means "not configured". An unrecognised name also returns
    ``None`` so a typo degrades to the caller's default rather than
    raising inside a seeding run.
    """
    if not isinstance(value, str):
        return None
    try:
        return Ide(value.strip().lower())
    except ValueError:
        return None


def _rules_for(*, config: dict, ide: Ide) -> IdeRules:
    def entries(key: str) -> tuple[str, ...]:
        block = config.get(key)
        if not isinstance(block, dict):
            return ()
        rules = block.get(ide.value)
        if not isinstance(rules, list):
            return ()
        return tuple(rule for rule in rules if isinstance(rule, str))

    return IdeRules(allow=entries(IDE_ALLOW_KEY), deny=entries(IDE_DENY_KEY))


def ide_inventory(*, config: dict) -> dict[Ide, IdeRules]:
    """Every IDE block the catalog defines, keyed by IDE."""
    return {ide: _rules_for(config=config, ide=ide) for ide in Ide}


def apply_ide_selection(*, config: dict, ide: Ide) -> dict:
    """Return ``config`` with only ``ide``'s rules folded into the flat lists.

    The input is not mutated: seeding runs read the shipped catalog from
    a cached loader, so mutating it would leak the first run's IDE into
    every later one in the same process.

    Idempotent — a rule already in the flat list is not duplicated.
    """
    rules = _rules_for(config=config, ide=ide)
    merged = dict(config)
    for key, additions in ((ALLOW_KEY, rules.allow), (DENY_KEY, rules.deny)):
        existing = [rule for rule in merged.get(key, []) if isinstance(rule, str)]
        merged[key] = existing + [rule for rule in additions if rule not in existing]
    return merged


__all__ = [
    "IDE_ALLOW_KEY",
    "IDE_DENY_KEY",
    "Ide",
    "IdeRules",
    "apply_ide_selection",
    "ide_inventory",
    "parse_ide",
]
