from __future__ import annotations

import pytest

from dev10x.domain.friction_level import FrictionLevel


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("strict", FrictionLevel.STRICT),
        ("guided", FrictionLevel.GUIDED),
        ("adaptive", FrictionLevel.ADAPTIVE),
        ("STRICT", FrictionLevel.STRICT),
        (" Adaptive ", FrictionLevel.ADAPTIVE),
    ],
)
def test_from_yaml_known(raw: str, expected: FrictionLevel) -> None:
    assert FrictionLevel.from_yaml(raw) is expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "bogus", 42, ["adaptive"], {"adaptive": True}],
)
def test_from_yaml_unknown_falls_back_to_default(raw: object) -> None:
    assert FrictionLevel.from_yaml(raw) is FrictionLevel.STRICT


def test_default_is_strict() -> None:
    assert FrictionLevel.default() is FrictionLevel.STRICT


def test_member_values_are_lowercase() -> None:
    for member in FrictionLevel:
        assert member.value == member.name.lower()


def test_str_enum_round_trips_through_yaml() -> None:
    assert FrictionLevel.ADAPTIVE == "adaptive"
    assert "adaptive" == FrictionLevel.ADAPTIVE.value


class TestPendingDecisionsGuidance:
    def test_adaptive_auto_selects(self) -> None:
        result = FrictionLevel.ADAPTIVE.pending_decisions_guidance()
        assert "auto-select" in result
        assert "without calling AskUserQuestion" in result

    def test_guided_asks_user(self) -> None:
        result = FrictionLevel.GUIDED.pending_decisions_guidance()
        assert "AskUserQuestion" in result
        assert "auto-select" not in result

    def test_strict_asks_user(self) -> None:
        result = FrictionLevel.STRICT.pending_decisions_guidance()
        assert "AskUserQuestion" in result
        assert "auto-select" not in result

    def test_all_members_return_non_empty(self) -> None:
        for member in FrictionLevel:
            assert member.pending_decisions_guidance()


class TestFallbackGuidanceIsGone:
    """GH-1194 collapsed the ADR-0002 command-redirect axis.

    `fallback_guidance()` existed only to vary the block message by that
    axis, and `skill_redirect` was its only caller. The clause is now
    unconditional there, so the method is gone — asserted rather than
    silently dropped, because a re-added method would quietly
    re-introduce the level-dependent branch.
    """

    def test_method_no_longer_exists(self) -> None:
        assert not hasattr(FrictionLevel.GUIDED, "fallback_guidance")
