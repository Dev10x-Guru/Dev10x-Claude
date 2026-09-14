"""GH-1288: a long tool call must end in a verdict, not a dropped socket."""

from __future__ import annotations

from dev10x.domain.transport_budget import (
    MAX_TOOL_CALL_SECONDS,
    MCP_IDLE_TIMEOUT_SECONDS,
    clamp_tool_timeout,
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
