from __future__ import annotations

from dataclasses import dataclass, field

from dev10x.domain.rules.validation_rule import MatchingRule


@dataclass(frozen=True)
class Config:
    """The parsed ``command-skill-map.yaml``.

    Carried a ``friction_level`` until GH-1194. That field was the
    ADR-0002 command-redirect axis — a different dial from the gate
    preset that happened to share the name — and only ``guided`` was
    ever shipped. It is collapsed: block messages always carry their
    fallback clause, and whether a rule blocks at all is per-rule
    ``hook_block``.
    """

    plugin_repo: str = ""
    rules: list[MatchingRule] = field(default_factory=list)
