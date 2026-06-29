"""Tests for the PolicyRule Protocol conformance (A9 / ADR-0007)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.documents.session_state import PlanSummary
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.rules.policy_rule import PolicyRule
from dev10x.domain.session_rules import (
    BuildAutonomyReassuranceRule,
    BuildAutoPlanGuidanceRule,
    CompletionRecommendation,
    DecisionGuidanceRule,
    completion_gate_recommendation,
    plan_gate_auto_approves,
)
from dev10x.hooks.session_policy import MigratePluginPermissionsRule


@pytest.mark.parametrize(
    "rule",
    [
        DecisionGuidanceRule(
            plan=PlanSummary.from_dict(data={}), friction_level=FrictionLevel.default()
        ),
        BuildAutonomyReassuranceRule(friction_level=FrictionLevel.default(), active_modes=[]),
        BuildAutoPlanGuidanceRule(friction_level=FrictionLevel.default(), active_modes=[]),
        MigratePluginPermissionsRule(plugin_root=Path("/p"), home_path=Path("/h")),
    ],
)
def test_policy_classes_satisfy_protocol(rule: PolicyRule) -> None:
    assert isinstance(rule, PolicyRule)


class TestPlanGateAutoApproves:
    """GH-678: single source of truth for the plan-approval gate decision."""

    @pytest.mark.parametrize(
        ("friction_level", "active_modes", "expected"),
        [
            # auto-plan auto-approves at EVERY friction level.
            (FrictionLevel.STRICT, ["auto-plan"], True),
            (FrictionLevel.GUIDED, ["auto-plan"], True),
            (FrictionLevel.ADAPTIVE, ["auto-plan"], True),
            # auto-plan composes with other modes without being cancelled.
            (FrictionLevel.GUIDED, ["solo-maintainer", "auto-plan"], True),
            # adaptive + solo-maintainer keeps the GH-252 bypass.
            (FrictionLevel.ADAPTIVE, ["solo-maintainer"], True),
            # The unreachable-cell cases: gate is NOT auto-approved.
            (FrictionLevel.GUIDED, [], False),
            (FrictionLevel.STRICT, [], False),
            (FrictionLevel.STRICT, ["solo-maintainer"], False),
            # adaptive WITHOUT solo-maintainer: widget still fires (veto).
            (FrictionLevel.ADAPTIVE, [], False),
            (FrictionLevel.GUIDED, ["solo-maintainer"], False),
        ],
    )
    def test_matrix(
        self,
        friction_level: FrictionLevel,
        active_modes: list[str],
        expected: bool,
    ) -> None:
        assert (
            plan_gate_auto_approves(friction_level=friction_level, active_modes=active_modes)
            is expected
        )


class TestCompletionGateRecommendation:
    """GH-729: completion is merge-gated — never recommend "Work complete"
    while an associated PR is open/unmerged."""

    @pytest.mark.parametrize(
        ("has_associated_pr", "pr_merged", "blocking_checks_pass", "expected"),
        [
            # Merged PR, checks green → complete.
            (True, True, True, CompletionRecommendation.WORK_COMPLETE),
            # No PR (investigation / local-only), checks green → complete.
            (False, False, True, CompletionRecommendation.WORK_COMPLETE),
            # Open, unmerged, otherwise green → monitor, NOT complete.
            (True, False, True, CompletionRecommendation.MONITOR_REVIEW),
            # Any blocking check failing → go back, regardless of PR state.
            (True, False, False, CompletionRecommendation.GO_BACK),
            (True, True, False, CompletionRecommendation.GO_BACK),
            (False, False, False, CompletionRecommendation.GO_BACK),
        ],
    )
    def test_matrix(
        self,
        has_associated_pr: bool,
        pr_merged: bool,
        blocking_checks_pass: bool,
        expected: CompletionRecommendation,
    ) -> None:
        assert (
            completion_gate_recommendation(
                has_associated_pr=has_associated_pr,
                pr_merged=pr_merged,
                blocking_checks_pass=blocking_checks_pass,
            )
            is expected
        )

    def test_open_unmerged_pr_never_recommends_work_complete(self) -> None:
        # The load-bearing GH-729 invariant.
        assert (
            completion_gate_recommendation(
                has_associated_pr=True,
                pr_merged=False,
                blocking_checks_pass=True,
            )
            is not CompletionRecommendation.WORK_COMPLETE
        )


class TestBuildAutoPlanGuidanceRule:
    """GH-678: SessionStart briefing fires only when auto-plan is active."""

    def test_emits_guidance_when_auto_plan_active(self) -> None:
        text = BuildAutoPlanGuidanceRule(
            friction_level=FrictionLevel.GUIDED, active_modes=["auto-plan"]
        ).apply()
        assert "`auto-plan` mode active" in text
        assert "STILL fire" in text

    def test_empty_without_auto_plan(self) -> None:
        text = BuildAutoPlanGuidanceRule(
            friction_level=FrictionLevel.GUIDED, active_modes=["solo-maintainer"]
        ).apply()
        assert text == ""

    def test_fires_regardless_of_friction_level(self) -> None:
        # auto-plan is a mode, not a level — present at strict too.
        text = BuildAutoPlanGuidanceRule(
            friction_level=FrictionLevel.STRICT, active_modes=["auto-plan"]
        ).apply()
        assert text != ""


class TestMigrateTwoPass:
    """GH-571: the migration rewrites all settings files via a
    validate-then-write two-pass (ADR-0011 Layer 4)."""

    def _setup(self, tmp_path: Path) -> tuple[MigratePluginPermissionsRule, Path, Path, str]:
        cache = tmp_path / ".claude" / "plugins" / "cache" / "Dev10x-Guru" / "Dev10x"
        old = cache / "0.78.0"
        new = cache / "0.79.0"
        old.mkdir(parents=True)
        new.mkdir(parents=True)
        old_abs = str(old) + "/"
        claude = tmp_path / ".claude"
        settings = claude / "settings.json"
        local = claude / "settings.local.json"
        settings.write_text(
            json.dumps({"permissions": {"allow": [f"Bash({old_abs}run.sh:*)"]}}, indent=2)
        )
        local.write_text(json.dumps({"permissions": {"allow": [f"Read({old_abs}x)"]}}, indent=2))
        rule = MigratePluginPermissionsRule(plugin_root=new, home_path=tmp_path)
        return rule, settings, local, str(new) + "/"

    def test_migrates_all_valid_files(self, tmp_path: Path) -> None:
        rule, settings, local, new_abs = self._setup(tmp_path)

        total, files = rule.apply()

        assert total == 2
        assert set(files) == {"settings.json", "settings.local.json"}
        assert new_abs in settings.read_text()
        assert new_abs in local.read_text()

    def test_corrupt_file_skipped_valid_file_still_migrated(self, tmp_path: Path) -> None:
        rule, settings, local, new_abs = self._setup(tmp_path)
        local.write_text("{corrupt json")

        total, files = rule.apply()

        assert total == 1
        assert files == ["settings.json"]
        assert new_abs in settings.read_text()
        # The corrupt file is never written — its bytes are untouched.
        assert local.read_text() == "{corrupt json"
