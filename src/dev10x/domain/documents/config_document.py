from __future__ import annotations

from dataclasses import dataclass, field

from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.rules.validation_rule import MatchingRule


@dataclass(frozen=True)
class Config:
    friction_level: FrictionLevel = FrictionLevel.STRICT
    plugin_repo: str = ""
    rules: list[MatchingRule] = field(default_factory=list)
