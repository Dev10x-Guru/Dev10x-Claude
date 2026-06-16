"""Unit tests for dev10x.github.pattern_validation (GH-348).

Contract class: mock
  Token matching and FP estimation are pure functions tested without
  mocks. The orchestrator patches the GH-346 miner and the diff helpers
  directly so no ``gh`` subprocess runs.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok

pv = pytest.importorskip("dev10x.github.pattern_validation", reason="dev10x not installed")


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _pattern(*, signature: str = "rename pm payment_method", frequency: int = 7) -> dict:
    return {"signature": signature, "frequency": frequency}


class TestAddedLineTokens:
    def test_only_added_lines_contribute(self) -> None:
        diff = "+++ b/a.py\n+def rename_payment_method():\n-old_line\n unchanged"
        tokens = pv._added_line_tokens(diff)
        assert "rename_payment_method" in tokens
        assert "old_line" not in tokens
        assert "unchanged" not in tokens

    def test_file_header_excluded(self) -> None:
        assert pv._added_line_tokens("+++ b/payment.py\n") == set()

    def test_punctuation_stripped_and_lowercased(self) -> None:
        assert pv._added_line_tokens("+  Payment_Method, pm = X()") == {
            "payment_method",
            "pm",
            "x",
        }


class TestPatternFires:
    def test_full_overlap_fires(self) -> None:
        assert pv.pattern_fires(signature="named parameters", diff_tokens={"named", "parameters"})

    def test_partial_overlap_above_threshold_fires(self) -> None:
        assert pv.pattern_fires(
            signature="a b c d e",
            diff_tokens={"a", "b", "c"},
            threshold=0.6,
        )

    def test_partial_overlap_below_threshold_does_not_fire(self) -> None:
        assert not pv.pattern_fires(
            signature="a b c d e",
            diff_tokens={"a"},
            threshold=0.6,
        )

    def test_empty_signature_never_fires(self) -> None:
        assert not pv.pattern_fires(signature="   ", diff_tokens={"a", "b"})


class TestEstimateFalsePositiveRate:
    def test_no_matches_is_zero(self) -> None:
        assert pv.estimate_false_positive_rate(frequency=5, diff_matches=0) == 0.0

    def test_matches_within_frequency_is_zero(self) -> None:
        assert pv.estimate_false_positive_rate(frequency=10, diff_matches=4) == 0.0

    def test_surplus_matches_yield_rate(self) -> None:
        assert pv.estimate_false_positive_rate(frequency=2, diff_matches=10) == 0.8


class TestValidatePatterns:
    def test_validated_when_frequent_and_low_fp(self) -> None:
        diffs = ["+ rename pm payment_method"]
        result = pv.validate_patterns(
            patterns=[_pattern(frequency=5)],
            diffs=diffs,
            min_frequency=2,
            max_fp_rate=0.5,
        )
        assert result[0].validated is True
        assert result[0].diff_matches == 1
        assert result[0].false_positive_rate == 0.0

    def test_rejected_when_below_min_frequency(self) -> None:
        result = pv.validate_patterns(
            patterns=[_pattern(frequency=1)],
            diffs=[],
            min_frequency=2,
            max_fp_rate=0.5,
        )
        assert result[0].validated is False

    def test_rejected_when_fp_rate_too_high(self) -> None:
        diffs = ["+ rename pm payment_method"] * 10
        result = pv.validate_patterns(
            patterns=[_pattern(frequency=1)],
            diffs=diffs,
            min_frequency=1,
            max_fp_rate=0.5,
        )
        assert result[0].false_positive_rate == 0.9
        assert result[0].validated is False

    def test_ordering_validated_first_then_fp_then_frequency(self) -> None:
        diffs = ["+ rename pm payment_method"]
        patterns = [
            {"signature": "unmatched signature here", "frequency": 1},
            _pattern(signature="rename pm payment_method", frequency=5),
        ]
        result = pv.validate_patterns(
            patterns=patterns,
            diffs=diffs,
            min_frequency=2,
            max_fp_rate=0.5,
        )
        assert result[0].validated is True
        assert result[0].signature == "rename pm payment_method"

    def test_to_dict_rounds_rate(self) -> None:
        diffs = ["+ rename pm payment_method"] * 3
        result = pv.validate_patterns(
            patterns=[_pattern(frequency=1)],
            diffs=diffs,
            min_frequency=1,
            max_fp_rate=1.0,
        )
        payload = result[0].to_dict()
        assert payload["false_positive_rate"] == 0.6667
        assert payload["diff_matches"] == 3
        assert payload["validated"] is True


class TestValidateCandidatePatterns:
    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation._recent_diffs", new_callable=AsyncMock)
    @patch("dev10x.github.review_patterns.cluster_review_comments", new_callable=AsyncMock)
    async def test_happy_path_validates_and_summarizes(
        self, mock_cluster: AsyncMock, mock_diffs: AsyncMock
    ) -> None:
        mock_cluster.return_value = ok(
            {
                "patterns": [_pattern(frequency=5)],
                "summary": {"repos_scanned": ["o/r"], "comments_analyzed": 8},
            }
        )
        mock_diffs.return_value = ["+ rename pm payment_method"]

        result = await pv.validate_candidate_patterns(repos=["o/r"])

        assert isinstance(result, SuccessResult)
        assert result.value["validated"][0]["validated"] is True
        assert result.value["summary"]["diffs_analyzed"] == 1
        assert result.value["summary"]["validated_count"] == 1
        mock_diffs.assert_awaited_once_with(repo="o/r", limit=20)

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.cluster_review_comments", new_callable=AsyncMock)
    async def test_propagates_mining_error(self, mock_cluster: AsyncMock) -> None:
        mock_cluster.return_value = err("no repository specified")

        result = await pv.validate_candidate_patterns()

        assert isinstance(result, ErrorResult)
        assert result.error == "no repository specified"


class TestRecentDiffs:
    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation._pr_diff", new_callable=AsyncMock)
    @patch("dev10x.github.pattern_validation._merged_pr_numbers", new_callable=AsyncMock)
    async def test_collects_non_empty_diffs(
        self, mock_numbers: AsyncMock, mock_diff: AsyncMock
    ) -> None:
        mock_numbers.return_value = ok([1, 2])
        mock_diff.side_effect = ["+ added one", None]

        diffs = await pv._recent_diffs(repo="o/r", limit=20)

        assert diffs == ["+ added one"]

    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation._merged_pr_numbers", new_callable=AsyncMock)
    async def test_returns_empty_on_number_lookup_error(self, mock_numbers: AsyncMock) -> None:
        mock_numbers.return_value = err("gh pr list failed")

        assert await pv._recent_diffs(repo="o/r", limit=20) == []


class TestMergedPrNumbers:
    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation.async_run", new_callable=AsyncMock)
    async def test_parses_numbers(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([{"number": 7}, {"number": 9}]))
        result = await pv._merged_pr_numbers(repo="o/r", limit=50)
        assert isinstance(result, SuccessResult)
        assert result.value == [7, 9]

    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation.async_run", new_callable=AsyncMock)
    async def test_error_on_nonzero_returncode(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="boom")
        result = await pv._merged_pr_numbers(repo="o/r", limit=50)
        assert isinstance(result, ErrorResult)
        assert result.error == "boom"

    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation.async_run", new_callable=AsyncMock)
    async def test_error_on_unparseable_json(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="not json")
        result = await pv._merged_pr_numbers(repo="o/r", limit=50)
        assert isinstance(result, ErrorResult)


class TestPrDiff:
    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation.async_run", new_callable=AsyncMock)
    async def test_returns_diff_text(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="+ added line")
        assert await pv._pr_diff(repo="o/r", pr_number=3) == "+ added line"

    @pytest.mark.asyncio
    @patch("dev10x.github.pattern_validation.async_run", new_callable=AsyncMock)
    async def test_returns_none_on_failure(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="404")
        assert await pv._pr_diff(repo="o/r", pr_number=3) is None
