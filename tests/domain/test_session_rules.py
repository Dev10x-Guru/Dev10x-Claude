"""Direct unit tests for ``dev10x.domain.session_rules`` (GH-833).

The session-policy rules here were previously exercised only end-to-end
through the SessionStart orchestrator, which masks wrong-branch bugs in
their branchy logic. These tests pin each rule's decision matrix
directly:

* ``completion_gate_recommendation`` — the three-boolean GH-729 matrix.
* ``DecisionGuidanceRule`` — resume-guidance branching + the
  unknown-friction-level guard (audit M7 #D2).
* ``BuildAutonomyReassuranceRule`` / ``BuildAutoPlanGuidanceRule`` —
  the mode/friction gates that decide whether a SessionStart segment
  renders.
* ``ModeGuardRule`` — the durable-overlay allow-list precedence
  (GH-805): whether a derived high-autonomy overlay survives the repo's
  ``allowed_overlays`` policy. The *config-source* precedence (new-style
  ``gate_preset`` vs legacy ``friction_level``) is gate_policy's concern
  and lives in ``test_gate_policy.py``.
"""

from __future__ import annotations

import pytest

from dev10x.domain.documents.session_state import PlanSummary
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.session_rules import (
    BuildAutonomyReassuranceRule,
    BuildAutoPlanGuidanceRule,
    CompletionRecommendation,
    DecisionGuidanceRule,
    ModeGuardRule,
    UnknownFrictionLevelError,
    completion_gate_recommendation,
)


def _plan(*, tasks: list[dict[str, object]]) -> PlanSummary:
    """Build a PlanSummary from raw task dicts (normalized in __post_init__)."""
    return PlanSummary(tasks=tasks)  # type: ignore[arg-type]


_PENDING_DECISION = {"id": "1", "status": "pending", "metadata": {"decision_needed": "strategy?"}}
_PENDING_PLAIN = {"id": "2", "status": "pending"}
_COMPLETED = {"id": "3", "status": "completed"}


class TestCompletionGateRecommendation:
    @pytest.mark.parametrize(
        "has_associated_pr,pr_merged,blocking_checks_pass,expected",
        [
            # A failing blocking check dominates regardless of PR state.
            (True, False, False, CompletionRecommendation.GO_BACK),
            (True, True, False, CompletionRecommendation.GO_BACK),
            (False, False, False, CompletionRecommendation.GO_BACK),
            # No PR (investigation / local-only) with green checks completes.
            (False, False, True, CompletionRecommendation.WORK_COMPLETE),
            # Merged PR with green checks completes.
            (True, True, True, CompletionRecommendation.WORK_COMPLETE),
            # Open, unmerged, otherwise-green PR → monitor for review.
            (True, False, True, CompletionRecommendation.MONITOR_REVIEW),
        ],
    )
    def test_matrix(
        self,
        has_associated_pr: bool,
        pr_merged: bool,
        blocking_checks_pass: bool,
        expected: CompletionRecommendation,
    ) -> None:
        result = completion_gate_recommendation(
            has_associated_pr=has_associated_pr,
            pr_merged=pr_merged,
            blocking_checks_pass=blocking_checks_pass,
        )
        assert result is expected

    @pytest.mark.parametrize(
        "solo_maintainer,adaptive,expected",
        [
            # Solo-maintainer + adaptive on an open, green PR → auto-merge
            # terminal (GH-883): no reviewer to wait for, no manual gate.
            (True, True, CompletionRecommendation.AUTO_MERGE),
            # Either half missing keeps the team behaviour: monitor for review.
            (True, False, CompletionRecommendation.MONITOR_REVIEW),
            (False, True, CompletionRecommendation.MONITOR_REVIEW),
            (False, False, CompletionRecommendation.MONITOR_REVIEW),
        ],
    )
    def test_solo_maintainer_adaptive_auto_merges_open_pr(
        self,
        solo_maintainer: bool,
        adaptive: bool,
        expected: CompletionRecommendation,
    ) -> None:
        result = completion_gate_recommendation(
            has_associated_pr=True,
            pr_merged=False,
            blocking_checks_pass=True,
            solo_maintainer=solo_maintainer,
            adaptive=adaptive,
        )
        assert result is expected

    @pytest.mark.parametrize(
        "has_associated_pr,pr_merged,blocking_checks_pass,expected",
        [
            # A failing blocking check still dominates the solo+adaptive branch.
            (True, False, False, CompletionRecommendation.GO_BACK),
            # A merged PR completes even under solo+adaptive — nothing to merge.
            (True, True, True, CompletionRecommendation.WORK_COMPLETE),
            # No PR completes even under solo+adaptive — nothing to merge.
            (False, False, True, CompletionRecommendation.WORK_COMPLETE),
        ],
    )
    def test_solo_maintainer_adaptive_does_not_override_terminal_states(
        self,
        has_associated_pr: bool,
        pr_merged: bool,
        blocking_checks_pass: bool,
        expected: CompletionRecommendation,
    ) -> None:
        result = completion_gate_recommendation(
            has_associated_pr=has_associated_pr,
            pr_merged=pr_merged,
            blocking_checks_pass=blocking_checks_pass,
            solo_maintainer=True,
            adaptive=True,
        )
        assert result is expected


class TestDecisionGuidanceRule:
    def test_unknown_friction_level_raises(self) -> None:
        rule = DecisionGuidanceRule(
            plan=_plan(tasks=[_PENDING_PLAIN]),
            friction_level="adaptive",  # type: ignore[arg-type]
        )
        with pytest.raises(UnknownFrictionLevelError):
            rule.apply()

    def test_remaining_tasks_no_decisions_returns_advance(self) -> None:
        rule = DecisionGuidanceRule(
            plan=_plan(tasks=[_PENDING_PLAIN]),
            friction_level=FrictionLevel.GUIDED,
        )
        result = rule.apply()
        assert "Auto-advance through the task list" in result

    def test_no_tasks_returns_empty(self) -> None:
        rule = DecisionGuidanceRule(
            plan=_plan(tasks=[_COMPLETED]),
            friction_level=FrictionLevel.GUIDED,
        )
        assert rule.apply() == ""

    @pytest.mark.parametrize(
        "friction_level",
        [FrictionLevel.STRICT, FrictionLevel.GUIDED, FrictionLevel.ADAPTIVE],
    )
    def test_pending_decisions_delegate_to_friction_guidance(
        self, friction_level: FrictionLevel
    ) -> None:
        rule = DecisionGuidanceRule(
            plan=_plan(tasks=[_PENDING_DECISION]),
            friction_level=friction_level,
        )
        assert rule.apply() == friction_level.pending_decisions_guidance()


class TestBuildAutonomyReassuranceRule:
    @pytest.mark.parametrize(
        "friction_level,active_modes",
        [
            (FrictionLevel.GUIDED, ["solo-maintainer"]),
            (FrictionLevel.STRICT, ["solo-maintainer"]),
            (FrictionLevel.ADAPTIVE, []),
            (FrictionLevel.ADAPTIVE, ["review-deferred"]),
        ],
    )
    def test_returns_empty_outside_autonomous_profile(
        self, friction_level: FrictionLevel, active_modes: list[str]
    ) -> None:
        rule = BuildAutonomyReassuranceRule(
            friction_level=friction_level, active_modes=active_modes
        )
        assert rule.apply() == ""

    def test_adaptive_solo_maintainer_returns_reassurance(self) -> None:
        rule = BuildAutonomyReassuranceRule(
            friction_level=FrictionLevel.ADAPTIVE, active_modes=["solo-maintainer"]
        )
        result = rule.apply()
        assert "Long task lists are by design" in result
        assert result == BuildAutonomyReassuranceRule.REASSURANCE_TEXT


class TestBuildAutoPlanGuidanceRule:
    @pytest.mark.parametrize(
        "active_modes",
        [[], ["solo-maintainer"], ["review-deferred", "swarm-child"]],
    )
    def test_returns_empty_without_auto_plan(self, active_modes: list[str]) -> None:
        rule = BuildAutoPlanGuidanceRule(
            friction_level=FrictionLevel.GUIDED, active_modes=active_modes
        )
        assert rule.apply() == ""

    def test_auto_plan_returns_guidance(self) -> None:
        rule = BuildAutoPlanGuidanceRule(
            friction_level=FrictionLevel.GUIDED, active_modes=["auto-plan"]
        )
        result = rule.apply()
        assert "`auto-plan` mode active" in result
        assert result == BuildAutoPlanGuidanceRule.GUIDANCE_TEXT


class TestModeGuardRule:
    def test_no_allow_list_returns_empty(self) -> None:
        rule = ModeGuardRule(
            active_modes=["solo-maintainer"], walk_away=True, allowed_overlays=None
        )
        assert rule.apply() == ""

    def test_forbidden_solo_maintainer_overlay_warns(self) -> None:
        rule = ModeGuardRule(
            active_modes=["solo-maintainer"], walk_away=False, allowed_overlays=[]
        )
        result = rule.apply()
        assert "Durable-mode guard" in result
        assert "solo-maintainer" in result

    def test_forbidden_afk_overlay_warns(self) -> None:
        rule = ModeGuardRule(active_modes=[], walk_away=True, allowed_overlays=["solo-maintainer"])
        result = rule.apply()
        assert "afk" in result

    def test_permitted_overlay_returns_empty(self) -> None:
        rule = ModeGuardRule(
            active_modes=["solo-maintainer"],
            walk_away=False,
            allowed_overlays=["solo-maintainer"],
        )
        assert rule.apply() == ""

    def test_no_derived_overlays_returns_empty(self) -> None:
        rule = ModeGuardRule(
            active_modes=["review-deferred"],
            walk_away=False,
            allowed_overlays=["solo-maintainer", "afk"],
        )
        assert rule.apply() == ""

    def test_names_only_the_dropped_overlay(self) -> None:
        # solo-maintainer derived but not allowed; afk derived and allowed.
        rule = ModeGuardRule(
            active_modes=["solo-maintainer"], walk_away=True, allowed_overlays=["afk"]
        )
        result = rule.apply()
        assert "solo-maintainer" in result
