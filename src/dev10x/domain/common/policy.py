"""Policy value object — a structured permission policy (GH-271).

Replaces the flat ``base_permissions`` string list with a typed model so
the permission catalog can be reasoned about along the three dimensions
GH-271 evidence converged on:

- **tier** — audience breadth (1 universal, 2 common dev tools, 3 opt-in),
  carried over from the grouped ``baseline-permissions.yaml`` catalog.
- **source** — who authored the rule (plugin default, user-private
  catalog, or project-local settings). Drives precedence and worktree
  forward-sync.
- **effect** — the Cedar-style decision (``allow`` / ``ask`` / ``deny``).
  The shipped baseline is an allow catalog, but the model carries the
  effect so the deny catalog and ask-tier work can build on it.

A :class:`Policy` wraps an :class:`AllowRule` (the canonical matching
value object) rather than reimplementing pattern matching. ``PolicyCatalog``
parses the existing grouped catalog YAML into ``Policy`` objects, mirroring
the missing/malformed-input tolerance of :class:`AllowRuleLoader`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.baseline_catalog import load_baseline_dict


class PolicyEffect(StrEnum):
    """Cedar-style decision a policy expresses for a matching tool call."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

    @classmethod
    def default(cls) -> PolicyEffect:
        """The baseline catalog is an allow catalog — ALLOW is the default."""
        return cls.ALLOW

    @classmethod
    def from_yaml(cls, raw: object) -> PolicyEffect:
        """Parse a raw YAML value into a PolicyEffect.

        Empty/unknown/non-string values fall back to :meth:`default`.
        Case-insensitive; trims surrounding whitespace.
        """
        return _parse_enum(cls, raw)


class PolicySource(StrEnum):
    """Provenance of a policy — drives precedence and worktree sync."""

    PLUGIN_DEFAULT = "plugin-default"
    USER_PRIVATE = "user-private"
    PROJECT_LOCAL = "project-local"

    @classmethod
    def default(cls) -> PolicySource:
        """Catalog rules without an explicit source are plugin defaults."""
        return cls.PLUGIN_DEFAULT

    @classmethod
    def from_yaml(cls, raw: object) -> PolicySource:
        """Parse a raw YAML value into a PolicySource.

        Empty/unknown/non-string values fall back to :meth:`default`.
        Case-insensitive; trims surrounding whitespace.
        """
        return _parse_enum(cls, raw)


def _parse_enum[E: StrEnum](enum_cls: type[E], raw: object) -> E:
    if not isinstance(raw, str):
        return enum_cls.default()  # type: ignore[attr-defined]
    normalized = raw.strip().lower()
    for member in enum_cls:
        if member.value == normalized:
            return member
    return enum_cls.default()  # type: ignore[attr-defined]


@dataclass(frozen=True)
class Policy:
    """One permission rule plus its tier, source, and effect."""

    rule: AllowRule
    tier: int
    source: PolicySource
    effect: PolicyEffect = PolicyEffect.ALLOW
    group: str = ""

    @property
    def signature(self) -> str:
        """The raw ``Tool(pattern)`` string this policy governs."""
        return self.rule.raw

    def matches(self, signature: str) -> bool:
        """Delegate matching to the wrapped :class:`AllowRule`."""
        return self.rule.matches(signature=signature)

    @classmethod
    def from_rule_str(
        cls,
        rule: str,
        *,
        tier: int,
        source: PolicySource,
        effect: PolicyEffect = PolicyEffect.ALLOW,
        group: str = "",
    ) -> Policy:
        return cls(
            rule=AllowRule.parse(rule),
            tier=tier,
            source=source,
            effect=effect,
            group=group,
        )


class PolicyCatalog:
    """Parses grouped ``baseline-permissions.yaml`` data into Policies."""

    @staticmethod
    def from_baseline_dict(
        data: dict,
        *,
        source: PolicySource = PolicySource.PLUGIN_DEFAULT,
    ) -> list[Policy]:
        """Flatten the catalog's ``groups`` into an ordered policy list.

        Each group contributes its ``rules`` as Policies carrying the
        group's ``tier`` (default ``0``), optional group-level ``effect``
        (default ``allow``), the group name, and the supplied ``source``.
        Malformed groups, missing/non-list ``rules``, and non-string rule
        entries are skipped rather than raising.
        """
        groups = data.get("groups")
        if not isinstance(groups, dict):
            return []
        policies: list[Policy] = []
        for name, group in groups.items():
            if not isinstance(group, dict):
                continue
            rules = group.get("rules")
            if not isinstance(rules, list):
                continue
            tier = group.get("tier", 0)
            effect = PolicyEffect.from_yaml(group.get("effect"))
            for rule in rules:
                if not isinstance(rule, str):
                    continue
                policies.append(
                    Policy.from_rule_str(
                        rule,
                        tier=tier,
                        source=source,
                        effect=effect,
                        group=name,
                    )
                )
        return policies

    @staticmethod
    def load(
        path: str | Path,
        *,
        source: PolicySource = PolicySource.PLUGIN_DEFAULT,
    ) -> list[Policy]:
        """Load a catalog YAML file into Policies.

        Returns ``[]`` for a missing file, unparseable YAML, or a
        top-level value that is not a mapping — mirroring
        :meth:`AllowRuleLoader.load`. Reading and parsing the baseline
        YAML is delegated to the shared loader (GH-587).
        """
        data = load_baseline_dict(Path(path), strict=False)
        return PolicyCatalog.from_baseline_dict(data, source=source)


__all__ = ["Policy", "PolicyCatalog", "PolicyEffect", "PolicySource"]
