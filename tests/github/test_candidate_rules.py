"""Unit tests for dev10x.github.candidate_rules (GH-347).

Contract class: mock
  Rendering is a pure function tested without mocks. The orchestrator
  patches the GH-346 miner (``cluster_review_comments``) directly so no
  ``gh`` subprocess runs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok

cr = pytest.importorskip("dev10x.github.candidate_rules", reason="dev10x not installed")


def _summary(
    *,
    repos: list[str] | None = None,
    analyzed: int = 8,
    returned: int = 2,
    top_n: int = 20,
) -> dict:
    return {
        "repos_scanned": repos if repos is not None else ["o/r"],
        "comments_analyzed": analyzed,
        "patterns_returned": returned,
        "top_n": top_n,
    }


def _pattern(
    *,
    signature: str = "rename pm payment_method",
    frequency: int = 7,
    files: list[str] | None = None,
    authors: list[str] | None = None,
    examples: list[str] | None = None,
) -> dict:
    return {
        "signature": signature,
        "frequency": frequency,
        "score": frequency,
        "files": files if files is not None else ["a.py", "b.py"],
        "authors": authors if authors is not None else ["al", "bo"],
        "examples": examples if examples is not None else ["rename pm to payment_method"],
    }


class TestSummarizeExample:
    def test_collapses_whitespace(self) -> None:
        assert cr._summarize_example("rename   pm\nto  payment_method") == (
            "rename pm to payment_method"
        )

    def test_short_body_unchanged(self) -> None:
        assert cr._summarize_example("short note") == "short note"

    def test_long_body_truncated_with_ellipsis(self) -> None:
        summarized = cr._summarize_example("x" * 200)
        assert summarized.endswith("…")
        assert len(summarized) <= cr._EXAMPLE_LIMIT


class TestJoinOrDash:
    def test_joins_values(self) -> None:
        assert cr._join_or_dash(["a.py", "b.py"]) == "a.py, b.py"

    def test_empty_yields_dash(self) -> None:
        assert cr._join_or_dash([]) == "—"


class TestRenderReport:
    def test_includes_read_only_note_and_header(self) -> None:
        report = cr.render_report(patterns=[_pattern()], summary=_summary())
        assert report.startswith("# Candidate Rules Report")
        assert "No rules were generated" in report

    def test_includes_summary_counts(self) -> None:
        report = cr.render_report(patterns=[_pattern()], summary=_summary(analyzed=8))
        assert "**Repositories scanned:** o/r" in report
        assert "**Merged-PR review comments analyzed:** 8" in report

    def test_ranks_patterns_with_plural_occurrences(self) -> None:
        report = cr.render_report(patterns=[_pattern(frequency=7)], summary=_summary())
        assert "### 1. `rename pm payment_method` — 7 occurrences" in report
        assert "- **Files:** a.py, b.py" in report
        assert "- **Authors:** al, bo" in report
        assert "- **Example:** rename pm to payment_method" in report

    def test_single_occurrence_is_singular(self) -> None:
        report = cr.render_report(patterns=[_pattern(frequency=1)], summary=_summary())
        assert "1 occurrence" in report
        assert "1 occurrences" not in report

    def test_missing_files_authors_render_dash(self) -> None:
        report = cr.render_report(
            patterns=[_pattern(files=[], authors=[])],
            summary=_summary(),
        )
        assert "- **Files:** —" in report
        assert "- **Authors:** —" in report

    def test_pattern_without_examples_omits_example_line(self) -> None:
        report = cr.render_report(patterns=[_pattern(examples=[])], summary=_summary())
        assert "**Example:**" not in report

    def test_empty_patterns_shows_placeholder(self) -> None:
        report = cr.render_report(patterns=[], summary=_summary(repos=[], returned=0))
        assert "No recurring patterns found" in report
        assert "**Repositories scanned:** —" in report


class TestCandidateRulesReport:
    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.cluster_review_comments", new_callable=AsyncMock)
    async def test_happy_path_renders_and_passes_through(self, mock_cluster: AsyncMock) -> None:
        patterns = [_pattern()]
        summary = _summary()
        mock_cluster.return_value = ok({"patterns": patterns, "summary": summary})

        result = await cr.candidate_rules_report(repos=["o/r"])

        assert isinstance(result, SuccessResult)
        assert result.value["patterns"] == patterns
        assert result.value["summary"] == summary
        assert result.value["report"].startswith("# Candidate Rules Report")

    @pytest.mark.asyncio
    @patch("dev10x.github.review_patterns.cluster_review_comments", new_callable=AsyncMock)
    async def test_propagates_mining_error(self, mock_cluster: AsyncMock) -> None:
        mock_cluster.return_value = err("no repository specified")

        result = await cr.candidate_rules_report()

        assert isinstance(result, ErrorResult)
        assert result.error == "no repository specified"
