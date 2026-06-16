"""Unit tests for dev10x.github.rule_confidence (GH-350).

Contract class: real
  Scoring and ranking are pure functions; the feedback store uses
  tmp_path real files. The default-path orchestrators patch
  Dev10xConfigDir.home to a tmp dir so no real config home is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult

rc = pytest.importorskip("dev10x.github.rule_confidence", reason="dev10x not installed")


class TestConfidenceScore:
    def test_no_feedback_is_zero(self) -> None:
        assert rc.confidence_score(catches=0, false_positives=0) == 0.0

    def test_more_evidence_outranks_less_at_same_precision(self) -> None:
        few = rc.confidence_score(catches=1, false_positives=0)
        many = rc.confidence_score(catches=5, false_positives=0)
        assert many > few

    def test_false_positives_lower_score(self) -> None:
        clean = rc.confidence_score(catches=5, false_positives=0)
        noisy = rc.confidence_score(catches=5, false_positives=5)
        assert noisy < clean


class TestRankRules:
    def test_orders_by_confidence_then_catches_then_id(self) -> None:
        feedback = [
            rc.RuleFeedback(rule_id="noisy", catches=2, false_positives=8),
            rc.RuleFeedback(rule_id="clean", catches=8, false_positives=0),
        ]
        ranked = rc.rank_rules(feedback=feedback)
        assert [rule.rule_id for rule in ranked] == ["clean", "noisy"]
        assert ranked[0].confidence > ranked[1].confidence

    def test_to_dict_rounds_confidence(self) -> None:
        ranked = rc.rank_rules(
            feedback=[rc.RuleFeedback(rule_id="r", catches=3, false_positives=1)]
        )
        payload = ranked[0].to_dict()
        assert payload["rule_id"] == "r"
        assert isinstance(payload["confidence"], float)
        assert len(str(payload["confidence"]).split(".")[-1]) <= 4


class TestRuleFeedback:
    def test_total_sums_tallies(self) -> None:
        assert rc.RuleFeedback(rule_id="r", catches=3, false_positives=2).total == 5


class TestFeedbackStore:
    def test_load_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert rc.load_feedback(store_path=tmp_path / "missing.json") == {}

    def test_save_then_load_round_trips(self, tmp_path: Path) -> None:
        store = tmp_path / "fb.json"
        rc.save_feedback(
            feedback={"r": rc.RuleFeedback(rule_id="r", catches=2, false_positives=1)},
            store_path=store,
        )
        loaded = rc.load_feedback(store_path=store)
        assert loaded["r"].catches == 2
        assert loaded["r"].false_positives == 1

    def test_record_catch_increments_and_persists(self, tmp_path: Path) -> None:
        store = tmp_path / "fb.json"
        rc.record_feedback(rule_id="r", outcome=rc.CATCH, store_path=store)
        updated = rc.record_feedback(rule_id="r", outcome=rc.CATCH, store_path=store)
        assert updated.catches == 2
        assert json.loads(store.read_text())["r"]["catches"] == 2

    def test_record_false_positive_increments(self, tmp_path: Path) -> None:
        store = tmp_path / "fb.json"
        updated = rc.record_feedback(rule_id="r", outcome=rc.FALSE_POSITIVE, store_path=store)
        assert updated.false_positives == 1

    def test_record_unknown_outcome_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown outcome"):
            rc.record_feedback(rule_id="r", outcome="maybe", store_path=tmp_path / "fb.json")


class TestRuleConfidenceReport:
    @pytest.mark.asyncio
    async def test_explicit_path_ranks_tracked_rules(self, tmp_path: Path) -> None:
        store = tmp_path / "fb.json"
        rc.save_feedback(
            feedback={"clean": rc.RuleFeedback(rule_id="clean", catches=5, false_positives=0)},
            store_path=store,
        )
        result = await rc.rule_confidence_report(store_path=str(store))
        assert isinstance(result, SuccessResult)
        assert result.value["summary"]["rules_tracked"] == 1
        assert result.value["ranked"][0]["rule_id"] == "clean"

    @pytest.mark.asyncio
    async def test_default_path_uses_config_home(self, tmp_path: Path) -> None:
        with patch.object(rc.Dev10xConfigDir, "home", return_value=tmp_path):
            result = await rc.rule_confidence_report()
        assert isinstance(result, SuccessResult)
        assert result.value["summary"]["store_path"] == str(tmp_path / rc._FEEDBACK_FILENAME)


class TestRecordRuleFeedback:
    @pytest.mark.asyncio
    async def test_records_catch(self, tmp_path: Path) -> None:
        store = tmp_path / "fb.json"
        result = await rc.record_rule_feedback(rule_id="r", outcome="catch", store_path=str(store))
        assert isinstance(result, SuccessResult)
        assert result.value["feedback"]["catches"] == 1

    @pytest.mark.asyncio
    async def test_unknown_outcome_returns_error(self, tmp_path: Path) -> None:
        result = await rc.record_rule_feedback(
            rule_id="r", outcome="maybe", store_path=str(tmp_path / "fb.json")
        )
        assert isinstance(result, ErrorResult)
        assert "unknown outcome" in result.error
