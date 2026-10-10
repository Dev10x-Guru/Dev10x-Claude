"""Repair Bash rules with a ``*`` before the trailing ``:*`` (GH-1503).

Claude Code reads the text before ``:*`` as a literal prefix, so such a
rule never matches and the harness warns about it at every startup
(GH-1472). What to do about it depends on which list it sits in:

- **allow** — dropped. The space form (``Bash(X *)``) would turn a grant
  that was never active into a real wildcard: ``..`` traversal, ``-c``
  injection, arbitrary hosts.
- **deny / ask** — rewritten to the space form the harness suggests.
  Widening a guardrail only guards more, while dropping it would remove
  one silently. A rewrite whose result is already listed collapses into
  it rather than duplicating.

The space form carries no ``:*``, so a second pass finds nothing to do.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.skills.permission.legacy_namespace import RULE_LISTS, RuleList


def is_unmatchable(rule: str) -> bool:
    return AllowRule.parse(rule).has_literal_star_prefix


def space_form(rule: str) -> str:
    """The rewrite Claude Code's startup warning suggests.

    ``Bash(mv * /dev/null:*)`` -> ``Bash(mv * /dev/null*)``, and a prefix
    already ending in ``*`` just loses its ``:*``:
    ``Bash(rm -rf /work/**:*)`` -> ``Bash(rm -rf /work/**)``.
    """
    prefix = AllowRule.parse(rule).pattern[: -len(":*")]
    return f"Bash({prefix if prefix.endswith('*') else prefix + '*'})"


@dataclass(frozen=True)
class StarPrefixFix:
    """One unmatchable rule and what became of it."""

    list_name: RuleList
    before: str
    after: str | None
    pruned: bool = False

    @property
    def dropped(self) -> bool:
        return self.after is None

    def describe(self) -> str:
        if self.after is None:
            return (
                f"{self.list_name}: dropped {self.before} "
                "(a `*` before `:*` never matches; the space form would widen it)"
            )
        if self.pruned:
            return f"{self.list_name}: pruned {self.before} ({self.after} already present)"
        return f"{self.list_name}: {self.before} -> {self.after}"


@dataclass(frozen=True)
class StarPrefixRepair:
    """Every unmatchable rule found in one settings document."""

    fixes: tuple[StarPrefixFix, ...] = ()

    @property
    def count(self) -> int:
        return len(self.fixes)

    @property
    def changed(self) -> bool:
        return self.count > 0

    def describe(self) -> list[str]:
        return [fix.describe() for fix in self.fixes]


def _repair_rules(
    *,
    list_name: RuleList,
    rules: list[Any],
) -> tuple[list[Any], list[StarPrefixFix]]:
    present = {rule for rule in rules if isinstance(rule, str)}
    repaired: list[Any] = []
    fixes: list[StarPrefixFix] = []
    for rule in rules:
        if not (isinstance(rule, str) and is_unmatchable(rule)):
            repaired.append(rule)
            continue
        if list_name == "allow":
            fixes.append(StarPrefixFix(list_name=list_name, before=rule, after=None))
            continue
        after = space_form(rule)
        pruned = after in present
        fixes.append(StarPrefixFix(list_name=list_name, before=rule, after=after, pruned=pruned))
        if not pruned:
            repaired.append(after)
            present.add(after)
    return repaired, fixes


def repair_star_prefix(data: dict[str, Any]) -> tuple[dict[str, Any], StarPrefixRepair]:
    """Return ``data`` with unmatchable rules repaired, and what changed.

    ``data`` is not mutated, so a dry run and a write share one code path.
    """
    repaired = copy.deepcopy(data)
    fixes: list[StarPrefixFix] = []
    permissions = repaired.get("permissions")
    if isinstance(permissions, dict):
        for list_name in RULE_LISTS:
            rules = permissions.get(list_name)
            if not isinstance(rules, list):
                continue
            permissions[list_name], list_fixes = _repair_rules(list_name=list_name, rules=rules)
            fixes.extend(list_fixes)
    return repaired, StarPrefixRepair(fixes=tuple(fixes))


__all__ = [
    "StarPrefixFix",
    "StarPrefixRepair",
    "is_unmatchable",
    "repair_star_prefix",
    "space_form",
]
