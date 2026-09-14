"""GH-1288: a long tool call must end in a verdict, not a dropped socket."""

from __future__ import annotations

from dev10x.domain.transport_budget import (
    MAX_TOOL_CALL_SECONDS,
    MCP_IDLE_TIMEOUT_SECONDS,
    clamp_tool_timeout,
    polls_within_budget,
)


class TestClampToolTimeout:
    def test_a_modest_request_is_honoured(self):
        budget = clamp_tool_timeout(600)

        assert budget.seconds == 600
        assert budget.was_clamped is False

    def test_a_request_past_the_budget_is_held_down(self):
        # The call that killed the server asked for 1500.
        budget = clamp_tool_timeout(1500)

        assert budget.seconds == MAX_TOOL_CALL_SECONDS
        assert budget.was_clamped is True

    def test_the_original_request_survives_the_clamp(self):
        # The caller is told what it asked for, so the message can
        # separate "suite needs longer than the transport allows" from
        # "suite hung".
        assert clamp_tool_timeout(1500).requested == 1500

    def test_a_request_exactly_at_the_budget_is_not_reported_as_clamped(self):
        budget = clamp_tool_timeout(MAX_TOOL_CALL_SECONDS)

        assert budget.was_clamped is False


class TestTheBudgetLeavesRoomToReport:
    """The margin is the point: a call that runs to the transport's own
    ceiling never gets to return anything, which is the failure."""

    def test_the_call_budget_sits_below_the_transport_ceiling(self):
        assert MAX_TOOL_CALL_SECONDS < MCP_IDLE_TIMEOUT_SECONDS

    def test_the_budget_does_not_exceed_the_observed_deaths(self):
        # Both observed deaths landed at ~1137s. A budget above that
        # would let the reported run die exactly as it did, which makes
        # the clamp cosmetic for the case that motivated it. This is the
        # floor the evidence supports — not a claim about the ceiling.
        assert MAX_TOOL_CALL_SECONDS <= 1137


class TestPollsWithinBudget:
    """A waiting tool has to stop polling early enough to answer."""

    def test_a_short_wait_gets_everything_it_asked_for(self):
        budget = polls_within_budget(requested=3, poll_interval=10, initial_wait=5, overhead=60)

        assert budget.polls == 3
        assert budget.was_clamped is False

    def test_a_long_wait_is_cut_to_what_the_ceiling_affords(self):
        # ci_check_status's defaults: 60s of settling, 30s between polls,
        # 60s of slack. 40 polls was 1320s — above the ceiling and above
        # both observed deaths.
        budget = polls_within_budget(requested=40, poll_interval=30, initial_wait=60, overhead=60)

        assert budget.polls == 32
        assert budget.was_clamped is True
        assert 60 + 30 * budget.polls + 60 <= MAX_TOOL_CALL_SECONDS

    def test_the_original_request_survives_the_clamp(self):
        # Same reason as the timeout clamp: "this PR's CI is slower than
        # the transport allows" is worth saying out loud.
        assert (
            polls_within_budget(
                requested=500, poll_interval=30, initial_wait=60, overhead=60
            ).requested
            == 500
        )

    def test_an_extravagant_request_buys_no_more_than_a_default_one(self):
        # The unbounded shape: 500 polls was a four-hour cap on a
        # transport that tolerates ~19 minutes.
        greedy = polls_within_budget(requested=500, poll_interval=30, initial_wait=60, overhead=60)
        ordinary = polls_within_budget(
            requested=40, poll_interval=30, initial_wait=60, overhead=60
        )

        assert greedy.polls == ordinary.polls

    def test_a_settling_wait_that_eats_the_budget_leaves_no_polls(self):
        # Rather than a negative count. The caller still gets its
        # fast-path probe; it simply does not get to loop.
        budget = polls_within_budget(
            requested=40, poll_interval=30, initial_wait=MAX_TOOL_CALL_SECONDS, overhead=60
        )

        assert budget.polls == 0

    def test_a_zero_interval_is_not_divided_by(self):
        budget = polls_within_budget(requested=7, poll_interval=0, initial_wait=60, overhead=60)

        assert budget.polls == 7
