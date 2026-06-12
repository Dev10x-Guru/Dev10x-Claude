"""Unit tests for dev10x.github.review_patterns (GH-346).

Contract class: mock
  Low-level fetch helpers patch ``async_run`` and supply canned ``gh``
  output. Orchestrators patch the fetch helpers directly. Clustering
  and normalization are pure and tested without mocks.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult

rp = pytest.importorskip("dev10x.github.review_patterns", reason="dev10x not installed")


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _comment(
    body: str, *, path: str = "", author: str = "", pr_number: int = 1
) -> rp.ReviewComment:
    return rp.ReviewComment(repo="o/r", pr_number=pr_number, body=body, path=path, author=author)


class TestNormalize:
    def test_strips_code_url_digits_and_punctuation(self) -> None:
        signature = rp._normalize(
            "Please rename `pm` to payment_method, see https://x.io item 42!"
        )
        assert "pm" not in signature.split()
        assert "http" not in signature
        assert "42" not in signature
        assert "rename" in signature

    def test_drops_stopwords(self) -> None:
        assert rp._normalize("this is the value") == "value"

    def test_code_only_body_yields_empty_signature(self) -> None:
        assert rp._normalize("```python\nx = 1\n```") == ""

    def test_truncates_to_signature_token_budget(self) -> None:
        signature = rp._normalize("alpha beta gamma delta epsilon zeta eta theta")
        assert len(signature.split()) == rp._SIGNATURE_TOKENS


class TestClusterAndScore:
    def test_groups_by_signature_and_counts_frequency(self) -> None:
        comments = [
            _comment("rename pm to payment_method", path="a.py", author="al"),
            _comment("rename pm to payment_method please", path="b.py", author="bo"),
            _comment("add a regression test", path="c.py", author="al"),
        ]
        patterns = rp.cluster_and_score(comments)
        assert patterns[0].frequency == 2
        assert patterns[0].files == ["a.py", "b.py"]
        assert patterns[0].authors == ["al", "bo"]
        assert len(patterns) == 2

    def test_skips_empty_signatures(self) -> None:
        patterns = rp.cluster_and_score([_comment("`code only`"), _comment("real feedback here")])
        assert len(patterns) == 1
        assert "real" in patterns[0].signature

    def test_ordering_frequency_then_files_then_signature(self) -> None:
        comments = [
            _comment("zzz frequent feedback", path="a.py"),
            _comment("zzz frequent feedback", path="b.py"),
            _comment("aaa rare feedback one", path="x.py"),
            _comment("aaa rare feedback one", path="x.py"),
        ]
        # both clusters have frequency 2; the one with more distinct files wins.
        patterns = rp.cluster_and_score(comments)
        assert patterns[0].signature.startswith("zzz")

    def test_examples_capped_at_three(self) -> None:
        comments = [_comment("same recurring note") for _ in range(5)]
        patterns = rp.cluster_and_score(comments)
        assert patterns[0].frequency == 5
        assert len(patterns[0].examples) == 3

    def test_top_n_truncates(self) -> None:
        comments = [_comment(f"distinct note number {chr(97 + i)}") for i in range(5)]
        patterns = rp.cluster_and_score(comments, top_n=2)
        assert len(patterns) == 2


class TestCandidatePattern:
    def test_score_equals_frequency_and_to_dict_shape(self) -> None:
        pattern = rp.CandidatePattern(
            signature="rename variable",
            frequency=3,
            files=["a.py"],
            authors=["al"],
            examples=["rename it"],
        )
        assert pattern.score == 3
        assert pattern.to_dict() == {
            "signature": "rename variable",
            "frequency": 3,
            "score": 3,
            "files": ["a.py"],
            "authors": ["al"],
            "examples": ["rename it"],
        }


class TestDetectRepo:
    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_returns_repo_on_success(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="owner/repo\n")
        assert await rp._detect_repo() == "owner/repo"

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_returns_none_on_failure(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="not a repo")
        assert await rp._detect_repo() is None

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_returns_none_on_empty_stdout(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="  \n")
        assert await rp._detect_repo() is None


class TestMergedPrNumbers:
    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_parses_numbers(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([{"number": 7}, {"number": 9}]))
        result = await rp._merged_pr_numbers(repo="o/r", limit=50)
        assert isinstance(result, SuccessResult)
        assert result.value == [7, 9]

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_error_on_nonzero_returncode(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="boom")
        result = await rp._merged_pr_numbers(repo="o/r", limit=50)
        assert isinstance(result, ErrorResult)
        assert result.error == "boom"

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_error_on_bad_json(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="not json")
        result = await rp._merged_pr_numbers(repo="o/r", limit=50)
        assert isinstance(result, ErrorResult)


class TestPrReviewComments:
    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_parses_comments(self, mock_run: AsyncMock) -> None:
        payload = [
            {"body": "rename this", "path": "a.py", "line": 4, "user": {"login": "al"}},
            {"body": "", "path": "b.py"},
        ]
        mock_run.return_value = _completed(stdout=json.dumps(payload))
        comments = await rp._pr_review_comments(repo="o/r", pr_number=3)
        assert len(comments) == 2
        assert comments[0].author == "al"
        assert comments[0].line == 4
        assert comments[1].author == ""

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_failed_fetch_returns_empty(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="403")
        assert await rp._pr_review_comments(repo="o/r", pr_number=3) == []

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.async_run", new_callable=AsyncMock)
    async def test_bad_json_returns_empty(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="<html>")
        assert await rp._pr_review_comments(repo="o/r", pr_number=3) == []


class TestFetchReviewComments:
    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns._pr_review_comments", new_callable=AsyncMock)
    @patch("dev10x.github.review_patterns._merged_pr_numbers", new_callable=AsyncMock)
    async def test_aggregates_across_prs(
        self,
        mock_numbers: AsyncMock,
        mock_comments: AsyncMock,
    ) -> None:
        from dev10x.domain.common.result import ok

        mock_numbers.return_value = ok([1, 2])
        mock_comments.side_effect = [[_comment("a", pr_number=1)], [_comment("b", pr_number=2)]]
        result = await rp.fetch_review_comments(repo="o/r", limit=50)
        assert isinstance(result, SuccessResult)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns._merged_pr_numbers", new_callable=AsyncMock)
    async def test_propagates_pr_list_error(self, mock_numbers: AsyncMock) -> None:
        from dev10x.domain.common.result import err

        mock_numbers.return_value = err("pr list failed")
        result = await rp.fetch_review_comments(repo="o/r", limit=50)
        assert isinstance(result, ErrorResult)
        assert result.error == "pr list failed"


class TestClusterReviewComments:
    @pytest.mark.asyncio
    async def test_rejects_non_positive_top_n(self) -> None:
        result = await rp.cluster_review_comments(repos=["o/r"], top_n=0)
        assert isinstance(result, ErrorResult)

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.fetch_review_comments", new_callable=AsyncMock)
    async def test_happy_path_returns_patterns_and_summary(self, mock_fetch: AsyncMock) -> None:
        from dev10x.domain.common.result import ok

        mock_fetch.return_value = ok(
            [_comment("rename pm to payment_method"), _comment("rename pm to payment_method")]
        )
        result = await rp.cluster_review_comments(repos=["o/r"])
        assert isinstance(result, SuccessResult)
        assert result.value["summary"]["comments_analyzed"] == 2
        assert result.value["summary"]["repos_scanned"] == ["o/r"]
        assert result.value["patterns"][0]["frequency"] == 2

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns._detect_repo", new_callable=AsyncMock)
    async def test_detects_repo_when_omitted(self, mock_detect: AsyncMock) -> None:
        from dev10x.domain.common.result import ok

        mock_detect.return_value = "auto/repo"
        with patch(
            "dev10x.github.review_patterns.fetch_review_comments",
            new_callable=AsyncMock,
            return_value=ok([]),
        ):
            result = await rp.cluster_review_comments()
        assert isinstance(result, SuccessResult)
        assert result.value["summary"]["repos_scanned"] == ["auto/repo"]

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns._detect_repo", new_callable=AsyncMock)
    async def test_error_when_no_repo_detected(self, mock_detect: AsyncMock) -> None:
        mock_detect.return_value = None
        result = await rp.cluster_review_comments()
        assert isinstance(result, ErrorResult)

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.fetch_review_comments", new_callable=AsyncMock)
    async def test_skips_repo_on_fetch_error(self, mock_fetch: AsyncMock) -> None:
        from dev10x.domain.common.result import err, ok

        mock_fetch.side_effect = [err("rate limited"), ok([_comment("good feedback note")])]
        result = await rp.cluster_review_comments(repos=["bad/repo", "good/repo"])
        assert isinstance(result, SuccessResult)
        assert result.value["summary"]["repos_scanned"] == ["good/repo"]
