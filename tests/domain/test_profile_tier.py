from __future__ import annotations

import pytest

from dev10x.domain.profile_tier import ProfileTier


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("minimal", ProfileTier.MINIMAL),
        ("standard", ProfileTier.STANDARD),
        ("strict", ProfileTier.STRICT),
        ("MINIMAL", ProfileTier.MINIMAL),
        (" Strict ", ProfileTier.STRICT),
    ],
)
def test_from_raw_known(raw: str, expected: ProfileTier) -> None:
    assert ProfileTier.from_raw(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "bogus", "STRIKT"])
def test_from_raw_unknown_falls_back_to_default(raw: str | None) -> None:
    assert ProfileTier.from_raw(raw) is ProfileTier.STANDARD


def test_default_is_standard() -> None:
    assert ProfileTier.default() is ProfileTier.STANDARD


def test_ordinal_ordering() -> None:
    assert ProfileTier.MINIMAL < ProfileTier.STANDARD < ProfileTier.STRICT


@pytest.mark.parametrize(
    "active,validator,expected",
    [
        (ProfileTier.MINIMAL, ProfileTier.MINIMAL, True),
        (ProfileTier.MINIMAL, ProfileTier.STANDARD, False),
        (ProfileTier.STANDARD, ProfileTier.MINIMAL, True),
        (ProfileTier.STANDARD, ProfileTier.STANDARD, True),
        (ProfileTier.STANDARD, ProfileTier.STRICT, False),
        (ProfileTier.STRICT, ProfileTier.MINIMAL, True),
        (ProfileTier.STRICT, ProfileTier.STANDARD, True),
        (ProfileTier.STRICT, ProfileTier.STRICT, True),
    ],
)
def test_includes_matrix(
    active: ProfileTier,
    validator: ProfileTier,
    expected: bool,
) -> None:
    assert active.includes(validator_tier=validator) is expected
