"""Tests for the session_stale predicate (ADR-0016 #753, GH-742 F1)."""

from __future__ import annotations

import pytest

from dev10x.domain.session_staleness import session_stale


class TestSessionStale:
    def test_matching_branch_is_fresh(self) -> None:
        assert session_stale(recorded_branch="user/GH-1/x", current_branch="user/GH-1/x") is False

    def test_mismatched_branch_is_stale(self) -> None:
        assert session_stale(recorded_branch="user/GH-1/x", current_branch="user/GH-2/y") is True

    def test_overlapping_tickets_are_fresh(self) -> None:
        assert (
            session_stale(
                recorded_branch=None,
                current_branch=None,
                recorded_tickets=["GH-1", "GH-2"],
                current_tickets=["GH-2"],
            )
            is False
        )

    def test_disjoint_tickets_are_stale(self) -> None:
        assert (
            session_stale(
                recorded_branch=None,
                current_branch=None,
                recorded_tickets=["GH-1"],
                current_tickets=["GH-9"],
            )
            is True
        )

    def test_no_recorded_identity_is_stale(self) -> None:
        # The GH-742 hazard: a bare/leftover session must not be trusted.
        assert session_stale(recorded_branch=None, current_branch="user/GH-1/x") is True

    def test_branch_match_wins_over_disjoint_tickets(self) -> None:
        assert (
            session_stale(
                recorded_branch="b",
                current_branch="b",
                recorded_tickets=["GH-1"],
                current_tickets=["GH-9"],
            )
            is False
        )

    @pytest.mark.parametrize(
        ("recorded_branch", "current_branch"),
        [("b", None), (None, "b"), ("", "")],
    )
    def test_partial_or_empty_branch_info_is_stale(
        self, recorded_branch: str | None, current_branch: str | None
    ) -> None:
        assert (
            session_stale(recorded_branch=recorded_branch, current_branch=current_branch) is True
        )
