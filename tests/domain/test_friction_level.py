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
