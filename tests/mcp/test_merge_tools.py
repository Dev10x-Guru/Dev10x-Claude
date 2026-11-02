from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.result import err, ok

from dev10x.mcp import server_cli as cli_server


class TestAuditHandoffReport:
    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.audit_handoff_report", new_callable=AsyncMock)
    async def test_delegates_report_and_pr_state(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"verdict": "accept", "accepted": True})

        result = await cli_server.audit_handoff_report(
            report={"head_sha": "abc"},
            pr_state={"state": "OPEN"},
        )

        assert result == {"verdict": "accept", "accepted": True}
        assert mock_fn.call_args.kwargs == {
            "report": {"head_sha": "abc"},
            "pr_state": {"state": "OPEN"},
        }

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.audit_handoff_report", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"verdict": "reject", "accepted": False})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.audit_handoff_report(report={}, pr_state={}, cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestReconcileFixesLinks:
    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.reconcile_fixes_links", new_callable=AsyncMock)
    async def test_delegates_every_argument(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"ok": True, "unbacked": []})

        result = await cli_server.reconcile_fixes_links(
            body="Fixes: #12",
            base="origin/develop",
            head="feature",
            repo_dir="/work/child",
            acknowledge=[7],
        )

        assert result == {"ok": True, "unbacked": []}
        assert mock_fn.call_args.kwargs == {
            "body": "Fixes: #12",
            "base": "origin/develop",
            "head": "feature",
            "repo_dir": "/work/child",
            "acknowledge": [7],
        }

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.reconcile_fixes_links", new_callable=AsyncMock)
    async def test_defaults_head_and_optional_arguments(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"ok": True})

        await cli_server.reconcile_fixes_links(body="", base="origin/develop")

        kwargs = mock_fn.call_args.kwargs
        assert kwargs["head"] == "HEAD"
        assert kwargs["repo_dir"] is None
        assert kwargs["acknowledge"] is None

    @pytest.mark.asyncio
    @patch("dev10x.coding.merge.reconcile_fixes_links", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("git log origin/develop..HEAD failed: bad ref")

        result = await cli_server.reconcile_fixes_links(body="", base="origin/develop")

        assert result["error"] == "git log origin/develop..HEAD failed: bad ref"
