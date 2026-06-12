from __future__ import annotations

import pytest

from dev10x.domain.common.rule_id import RULE_ID_PATTERN, RuleId


class TestParse:
    @pytest.mark.parametrize(
        "raw,canonical",
        [
            ("DX001", "DX001"),
            ("dx042", "DX042"),
            ("Dx015", "DX015"),
        ],
    )
    def test_parses_and_normalises_case(self, raw: str, canonical: str) -> None:
        rule = RuleId.parse(raw)

        assert str(rule) == canonical
        assert rule.value == canonical

    @pytest.mark.parametrize(
        "raw",
        ["", "DX42", "DX0001", "EX001", "DX", "001", "DX001 ", "DXabc"],
    )
    def test_rejects_invalid_forms(self, raw: str) -> None:
        with pytest.raises(ValueError):
            RuleId.parse(raw)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            RuleId.parse(None)  # type: ignore[arg-type]


class TestDirectConstruction:
    def test_requires_canonical_uppercase(self) -> None:
        assert RuleId("DX001").value == "DX001"

    @pytest.mark.parametrize("raw", ["dx001", "DX42", ""])
    def test_rejects_non_canonical(self, raw: str) -> None:
        with pytest.raises(ValueError):
            RuleId(raw)


class TestTryParse:
    def test_returns_rule_on_success(self) -> None:
        assert RuleId.try_parse("dx009") == RuleId("DX009")

    def test_returns_none_on_failure(self) -> None:
        assert RuleId.try_parse("DX42") is None


class TestEquality:
    def test_case_insensitive_via_parse(self) -> None:
        assert RuleId.parse("dx001") == RuleId.parse("DX001")

    def test_hashable_by_canonical_value(self) -> None:
        assert {RuleId.parse("dx001"), RuleId.parse("DX001")} == {RuleId("DX001")}


def test_pattern_exposed_as_string() -> None:
    assert RULE_ID_PATTERN == r"DX\d{3}"
