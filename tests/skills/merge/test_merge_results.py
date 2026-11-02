from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x.coding.merge import audit_handoff_report, reconcile_fixes_links

HEAD = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"


def _completed(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _report(**overrides: object) -> dict[str, object]:
    return {
        "pr": "Dev10x-Guru/Dev10x-Claude#1362",
        "head_sha": HEAD,
        "measured_at": datetime.now(UTC).isoformat(),
        "checks": ["Check 3 isDraft: false", "Check 4 mergeable: MERGEABLE"],
        "blocked_gate": "Check 2 infrastructure override",
        "blocked_evidence": "claude-review failed on 'Credit balance is too low'",
        **overrides,
    }


class TestAuditHandoffReport:
    @pytest.mark.asyncio
    async def test_a_fresh_matching_report_is_accepted(self) -> None:
        result = await audit_handoff_report(
            report=_report(),
            pr_state={"state": "OPEN", "headRefOid": HEAD, "mergedAt": None},
        )

        assert isinstance(result, SuccessResult)
        assert result.value["verdict"] == "accept"
        assert result.value["accepted"] is True
        assert result.value["reasons"] == []

    @pytest.mark.asyncio
    async def test_a_moved_head_is_rejected_with_reasons(self) -> None:
        result = await audit_handoff_report(
            report=_report(),
            pr_state={"state": "OPEN", "headRefOid": "f" * 40, "mergedAt": None},
        )

        assert isinstance(result, SuccessResult)
        assert result.value["accepted"] is False
        assert any("head SHA moved" in reason for reason in result.value["reasons"])

    @pytest.mark.asyncio
    async def test_a_merged_pr_reports_already_merged(self) -> None:
        result = await audit_handoff_report(
            report=_report(),
            pr_state={
                "state": "MERGED",
                "headRefOid": HEAD,
                "mergedAt": "2026-09-16T11:50:00Z",
                "mergedBy": {"login": "octocat"},
            },
        )

        assert isinstance(result, SuccessResult)
        assert result.value["verdict"] == "already_merged"
        assert result.value["merged_at"] == "2026-09-16T11:50:00Z"
        assert result.value["summary"]


class TestReconcileFixesLinks:
    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.async_run", new_callable=AsyncMock)
    async def test_a_link_backed_by_a_commit_passes(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="✨ GH-12 Enable X\n\x00")

        result = await reconcile_fixes_links(body="Fixes: #12", base="origin/develop")

        assert isinstance(result, SuccessResult)
        assert result.value["ok"] is True
        assert result.value["delivered"] == [12]
        assert result.value["commits_read"] == 1

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.async_run", new_callable=AsyncMock)
    async def test_a_link_without_a_commit_is_unbacked(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="✨ GH-12 Enable X\n\x00")

        result = await reconcile_fixes_links(
            body="Fixes: #12\nFixes: #13",
            base="origin/develop",
        )

        assert isinstance(result, SuccessResult)
        assert result.value["ok"] is False
        assert result.value["unbacked"] == [13]
        assert "hint" not in result.value

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.async_run", new_callable=AsyncMock)
    async def test_an_acknowledged_link_is_not_unbacked(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="✨ GH-12 Enable X\n\x00")

        result = await reconcile_fixes_links(
            body="Fixes: #12\nFixes: #13",
            base="origin/develop",
            acknowledge=[13],
        )

        assert isinstance(result, SuccessResult)
        assert result.value["ok"] is True

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.async_run", new_callable=AsyncMock)
    async def test_an_empty_range_carries_the_wrong_checkout_hint(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = _completed(stdout="")

        result = await reconcile_fixes_links(
            body="Fixes: #12",
            base="origin/develop",
            repo_dir="/work/child",
        )

        assert isinstance(result, SuccessResult)
        assert result.value["commits_read"] == 0
        assert "/work/child" in result.value["hint"]

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.async_run", new_callable=AsyncMock)
    async def test_reads_the_range_in_repo_dir(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(stdout="")

        await reconcile_fixes_links(
            body="",
            base="origin/develop",
            head="feature",
            repo_dir="/work/child",
        )

        assert mock_run.call_args.kwargs["args"] == [
            "git",
            "log",
            "--format=%B%x00",
            "origin/develop..feature",
        ]
        assert mock_run.call_args.kwargs["cwd"] == "/work/child"

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.async_run", new_callable=AsyncMock)
    async def test_a_failed_git_log_is_an_error(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = _completed(returncode=128, stderr="unknown revision")

        result = await reconcile_fixes_links(body="Fixes: #12", base="origin/nope")

        assert isinstance(result, ErrorResult)
        assert "unknown revision" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.async_run", new_callable=AsyncMock)
    async def test_a_relative_repo_dir_is_refused_before_git_runs(
        self,
        mock_run: AsyncMock,
    ) -> None:
        result = await reconcile_fixes_links(
            body="Fixes: #12",
            base="origin/develop",
            repo_dir="child",
        )

        assert isinstance(result, ErrorResult)
        assert "absolute" in result.error
        mock_run.assert_not_awaited()
