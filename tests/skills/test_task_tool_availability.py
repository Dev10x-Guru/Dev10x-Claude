"""A missing task tool is a configuration, not a failure (GH-1055).

`TaskCreate` / `TaskGet` / `TaskUpdate` / `TaskList` / `TodoWrite` ship
by default only on Claude 3.x, Opus 4-4.7, Sonnet 4-4.6 and Haiku 4.5.
Every newer model — and any model ID Claude Code does not recognise —
omits them unless the user opts in.

132 files across `skills/`, `src/`, `.claude/`, `references/` and
`agents/` mandate `TaskCreate`. Exactly one acknowledged it might be
absent, and its answer was to stop: `Dev10x:work-on`, the plugin's main
orchestrator, refused to run at all on a default session of the models
it will most often meet.

These tests pin the replacement. The contract is stated once, in the
rule every session loads, and the orchestrator points at it instead of
carrying its own half of the answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_ESSENTIALS = _ROOT / ".claude" / "rules" / "essentials.md"
_WORK_ON = _ROOT / "skills" / "work-on" / "instructions.md"

_SECTION = "When the task tools are absent"


@pytest.fixture
def essentials() -> str:
    return _ESSENTIALS.read_text(encoding="utf-8")


@pytest.fixture
def work_on() -> str:
    return _WORK_ON.read_text(encoding="utf-8")


class TestTheContractIsStatedOnce:
    def test_the_always_loaded_rule_carries_the_section(self, essentials: str) -> None:
        assert _SECTION in essentials

    @pytest.mark.parametrize(
        "model_class",
        ["Claude 3.x", "Opus 4–4.7", "Sonnet 4–4.6", "Haiku 4.5"],
    )
    def test_it_names_which_models_still_ship_the_tools(
        self, essentials: str, model_class: str
    ) -> None:
        # A reader who cannot tell whether their own model is affected
        # cannot act on the rule.
        assert model_class in essentials

    def test_it_prescribes_the_transcript_fallback(self, essentials: str) -> None:
        assert "written checklist" in essentials

    def test_it_keeps_verify_ac_as_the_closing_obligation(self, essentials: str) -> None:
        # The invariant's point is that the agent never self-declares
        # done. Losing the task list must not lose that.
        section = essentials.split(_SECTION, 1)[1]
        assert "Verify AC" in section

    def test_it_admits_what_the_fallback_costs(self, essentials: str) -> None:
        # A rule that implies parity with the real task list invites a
        # supervisor to expect an insertion point that does not exist.
        section = essentials.split(_SECTION, 1)[1]
        assert "degradation" in section

    def test_it_says_plan_sync_identity_survives(self, essentials: str) -> None:
        # plan_sync_* are MCP tools, not task tools. Without this, the
        # next reader over-corrects and rebuilds machinery that works.
        section = essentials.split(_SECTION, 1)[1]
        assert "plan_sync" in section


class TestTheOrchestratorNoLongerStops:
    def test_work_on_does_not_refuse_to_run(self, work_on: str) -> None:
        assert "STOP and inform the" not in work_on

    def test_work_on_points_at_the_rule_rather_than_restating_it(self, work_on: str) -> None:
        assert _SECTION in work_on
        assert "essentials.md" in work_on

    def test_work_on_still_stops_when_an_offered_tool_fails(self, work_on: str) -> None:
        # Absent-by-design and advertised-but-broken are different. The
        # first is a configuration to run in; the second is a fault, and
        # degrading past it hides it.
        assert "present and fails is a different case" in work_on

    def test_work_on_explains_why_phase_0_5_can_never_resume(self, work_on: str) -> None:
        # The hook matchers are inert on such a model, so plan.tasks is
        # always empty — correct behaviour that reads like a bug.
        assert "plan.tasks" in work_on
