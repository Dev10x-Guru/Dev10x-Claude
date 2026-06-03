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


class TestFallbackGuidance:
    def test_guided_returns_fallback(self) -> None:
        result = FrictionLevel.GUIDED.fallback_guidance(fallback="try this instead")
        assert result == "try this instead"

    def test_strict_returns_empty(self) -> None:
        result = FrictionLevel.STRICT.fallback_guidance(fallback="try this instead")
        assert result == ""

    def test_adaptive_returns_empty(self) -> None:
        result = FrictionLevel.ADAPTIVE.fallback_guidance(fallback="try this instead")
        assert result == ""

    def test_guided_with_empty_fallback_returns_empty(self) -> None:
        result = FrictionLevel.GUIDED.fallback_guidance(fallback="")
        assert result == ""
