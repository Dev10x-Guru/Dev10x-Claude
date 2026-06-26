"""Tests for work-on bundled-execution batch detection (GH-248 G3 / GH-196)."""

from __future__ import annotations

import pytest

from dev10x.skills.orchestration.batch_detection import (
    MAX_BATCH_SIZE,
    OverlapSignal,
    group_into_batches,
    tickets_share_batch,
)

S = OverlapSignal


class TestTicketsShareBatch:
    @pytest.mark.parametrize(
        ("signals", "expected"),
        [
            (set(), False),
            ({S.SHARED_COMPONENT}, False),
            ({S.SHARED_COMPONENT, S.REPEATED_LABEL}, True),
            ({S.SHARED_COMPONENT, S.SHARED_ERROR_CLASS, S.SAME_PARENT}, True),
        ],
    )
    def test_threshold_is_two_signals(self, signals: set[OverlapSignal], expected: bool):
        assert tickets_share_batch(shared_signals=signals) is expected

    def test_duplicate_signals_do_not_count_twice(self):
        assert (
            tickets_share_batch(shared_signals=[S.SHARED_COMPONENT, S.SHARED_COMPONENT]) is False
        )


class TestGroupIntoBatches:
    def test_no_overlap_yields_singletons(self):
        batches = group_into_batches(tickets=["GH-1", "GH-2", "GH-3"], pair_signals={})
        assert batches == [["GH-1"], ["GH-2"], ["GH-3"]]

    def test_two_signal_pair_shares_a_batch(self):
        batches = group_into_batches(
            tickets=["GH-12", "GH-14", "GH-21"],
            pair_signals={
                ("GH-12", "GH-14"): {S.SHARED_COMPONENT, S.REPEATED_LABEL},
            },
        )
        assert batches == [["GH-12", "GH-14"], ["GH-21"]]

    def test_single_signal_pair_does_not_merge(self):
        batches = group_into_batches(
            tickets=["GH-1", "GH-2"],
            pair_signals={("GH-1", "GH-2"): {S.SHARED_COMPONENT}},
        )
        assert batches == [["GH-1"], ["GH-2"]]

    def test_signal_lookup_is_order_independent(self):
        batches = group_into_batches(
            tickets=["GH-1", "GH-2"],
            pair_signals={("GH-2", "GH-1"): {S.SAME_PARENT, S.REPEATED_LABEL}},
        )
        assert batches == [["GH-1", "GH-2"]]

    def test_batch_never_exceeds_max_size(self):
        tickets = [f"GH-{n}" for n in range(MAX_BATCH_SIZE + 2)]
        pair_signals = {
            (a, b): {S.SHARED_COMPONENT, S.REPEATED_LABEL}
            for a in tickets
            for b in tickets
            if a != b
        }
        batches = group_into_batches(tickets=tickets, pair_signals=pair_signals)
        assert len(batches[0]) == MAX_BATCH_SIZE
        assert batches[1] == tickets[MAX_BATCH_SIZE:]

    def test_empty_ticket_list_yields_empty_batches(self):
        batches = group_into_batches(tickets=[], pair_signals={})
        assert batches == []

    def test_chain_join_three_tickets_into_one_batch(self):
        # A-B share signals, B-C share signals → all three land in one batch.
        batches = group_into_batches(
            tickets=["A", "B", "C"],
            pair_signals={
                ("A", "B"): {S.SHARED_COMPONENT, S.SAME_PARENT},
                ("B", "C"): {S.SHARED_COMPONENT, S.REPEATED_LABEL},
            },
        )
        assert batches == [["A", "B", "C"]]

    def test_all_five_signals_qualify(self):
        all_signals = set(OverlapSignal)
        assert tickets_share_batch(shared_signals=all_signals) is True

    def test_explicit_reference_alone_is_insufficient(self):
        assert tickets_share_batch(shared_signals={S.EXPLICIT_REFERENCE}) is False

    def test_explicit_reference_plus_one_qualifies(self):
        assert (
            tickets_share_batch(shared_signals={S.EXPLICIT_REFERENCE, S.SHARED_COMPONENT}) is True
        )
