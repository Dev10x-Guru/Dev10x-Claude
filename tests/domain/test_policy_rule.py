"""Tests for the PolicyRule Protocol conformance (A9 / ADR-0007)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.rules.policy_rule import PolicyRule
from dev10x.domain.session_rules import DecisionGuidanceRule, ReadFrictionLevelRule
from dev10x.hooks.session_policy import (
    BuildAutonomyReassuranceRule,
    MigratePluginPermissionsRule,
)


@pytest.mark.parametrize(
    "rule",
    [
        ReadFrictionLevelRule(toplevel="/tmp"),
        DecisionGuidanceRule(plan={}, friction_level=FrictionLevel.default()),
        BuildAutonomyReassuranceRule(toplevel="/tmp"),
        MigratePluginPermissionsRule(plugin_root=Path("/p"), home_path=Path("/h")),
    ],
)
def test_policy_classes_satisfy_protocol(rule: PolicyRule) -> None:
    assert isinstance(rule, PolicyRule)
