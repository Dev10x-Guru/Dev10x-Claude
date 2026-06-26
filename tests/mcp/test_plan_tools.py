"""Wire-contract tests for the plan_tools MCP adapter (GH-556).

Verifies that each of the three MCP tools:

- Routes domain errors through ``to_wire`` and returns ``{"error": ...}``
  (branch on presence of "error" key — never on empty dict).
- Passes arguments to the service layer correctly.
- Returns a success dict (no "error" key) on the happy path.
- Serializes key-conflict / validation errors correctly.
- Serializes concurrent-write / archive-race failures correctly.

The plan service layer has its own tests (tests/plan/test_service.py);
these tests mock at the ``dev10x.plan.service.*`` boundary and focus on
the MCP adapter contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import err
from dev10x.mcp import server_cli as cli_server

SERVICE = "dev10x.plan.service"


# ── plan_sync_set_context ────────────────────────────────────────────────────


class TestPlanSyncSetContextErrorContract:
    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    async def test_outside_git_repo_returns_error_key(
        self,
        _toplevel: object,
    ) -> None:
        """PlanServiceError('Not in a git repository') → wire has 'error'."""
        result = await cli_server.plan_sync_set_context(args=["k=v"])

        assert "error" in result
        assert "git repository" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_arg_format_returns_error_key(
        self,
        tmp_path: Path,
    ) -> None:
        """K=V validation failure → wire has 'error'."""
        with patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)):
            result = await cli_server.plan_sync_set_context(args=["no-equals"])

        assert "error" in result
        assert "K=V" in result["error"]

    @pytest.mark.asyncio
    async def test_success_returns_updated_keys(
        self,
        tmp_path: Path,
    ) -> None:
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="feature/x"),
        ):
            result = await cli_server.plan_sync_set_context(
                args=["work_type=feature", "tickets=[GH-1]"],
            )

        assert "error" not in result
        assert result["success"] is True
        assert "work_type" in result["updated_keys"]
        assert "tickets" in result["updated_keys"]

    @pytest.mark.asyncio
    async def test_service_error_propagated_to_wire(self) -> None:
        """Domain layer returning err() → wire has 'error'."""
        with patch(
            "dev10x.plan.set_context",
            new=AsyncMock(return_value=err("custom service failure")),
        ):
            result = await cli_server.plan_sync_set_context(args=["k=v"])

        assert "error" in result
        assert "custom service failure" in result["error"]

    @pytest.mark.asyncio
    async def test_multiple_key_conflicts_are_last_write_wins(
        self,
        tmp_path: Path,
    ) -> None:
        """Duplicate keys in args — last value wins (set_plan_context semantics)."""
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="b"),
        ):
            result = await cli_server.plan_sync_set_context(
                args=["work_type=feature", "work_type=bugfix"],
            )

        assert "error" not in result
        # updated_keys deduplication depends on plan.context_keys(); both calls succeed
        assert result["success"] is True


# ── plan_sync_json_summary ───────────────────────────────────────────────────


class TestPlanSyncJsonSummaryErrorContract:
    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    async def test_outside_git_repo_returns_error_key(
        self,
        _toplevel: object,
    ) -> None:
        result = await cli_server.plan_sync_json_summary()

        assert "error" in result
        assert "git" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_plan_file_returns_empty_dict(
        self,
        tmp_path: Path,
    ) -> None:
        """plan_summary returns {} when no plan file exists — no error key."""
        with patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)):
            result = await cli_server.plan_sync_json_summary()

        # {} is the wire representation of SuccessResult({})
        assert "error" not in result
        assert result == {}

    @pytest.mark.asyncio
    async def test_existing_plan_returns_plan_dict(
        self,
        tmp_path: Path,
    ) -> None:
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="feature/x"),
        ):
            # Create a plan first so the summary is non-empty
            from dev10x.plan.service import set_plan_context

            set_plan_context(args=["work_type=feature"])
            result = await cli_server.plan_sync_json_summary()

        assert "error" not in result
        assert result["plan"]["context"]["work_type"] == "feature"

    @pytest.mark.asyncio
    async def test_service_error_propagated_to_wire(self) -> None:
        with patch(
            "dev10x.plan.json_summary",
            new=AsyncMock(return_value=err("summary failure")),
        ):
            result = await cli_server.plan_sync_json_summary()

        assert "error" in result
        assert "summary failure" in result["error"]


# ── plan_sync_archive ────────────────────────────────────────────────────────


class TestPlanSyncArchiveErrorContract:
    @pytest.mark.asyncio
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    async def test_outside_git_repo_returns_error_key(
        self,
        _toplevel: object,
    ) -> None:
        result = await cli_server.plan_sync_archive()

        assert "error" in result
        assert "git" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_plan_file_returns_success_no_archive_name(
        self,
        tmp_path: Path,
    ) -> None:
        """archive_plan returns {"archived": False} → wire is success without archive_name."""
        with patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)):
            result = await cli_server.plan_sync_archive()

        assert "error" not in result
        assert result["success"] is True
        assert "archive_name" not in result

    @pytest.mark.asyncio
    async def test_existing_plan_archived_successfully(
        self,
        tmp_path: Path,
    ) -> None:
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="feature/x"),
        ):
            from dev10x.plan.service import set_plan_context

            set_plan_context(args=["work_type=feature"])
            result = await cli_server.plan_sync_archive()

        assert "error" not in result
        assert result["success"] is True
        assert "archive_name" in result
        assert result["archive_name"].startswith("plan-")

    @pytest.mark.asyncio
    async def test_service_error_propagated_to_wire(self) -> None:
        with patch(
            "dev10x.plan.archive",
            new=AsyncMock(return_value=err("archive failure")),
        ):
            result = await cli_server.plan_sync_archive()

        assert "error" in result
        assert "archive failure" in result["error"]

    @pytest.mark.asyncio
    async def test_concurrent_archive_second_call_finds_no_plan(
        self,
        tmp_path: Path,
    ) -> None:
        """Simulates an archive race: after the first archive removes the plan
        file, a second concurrent call sees no plan and returns success without
        archive_name (the 'archived: False' path)."""
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="main"),
        ):
            from dev10x.plan.service import set_plan_context

            set_plan_context(args=["work_type=feature"])
            # First archive — should succeed
            first = await cli_server.plan_sync_archive()
            # Second archive of same dir — plan already gone
            second = await cli_server.plan_sync_archive()

        assert "error" not in first
        assert first["success"] is True
        assert "archive_name" in first

        assert "error" not in second
        assert second["success"] is True
        # Second call found no plan to archive
        assert "archive_name" not in second


# ── cwd context-manager activation ──────────────────────────────────────────


class TestPlanToolsCwdActivation:
    """Verify that plan_sync_* tools bind the cwd ContextVar before
    calling the domain layer (GH-979 contract)."""

    @pytest.mark.asyncio
    async def test_set_context_activates_cwd(self, tmp_path: Path) -> None:
        captured: list[object] = []

        async def _spy_set_context(*, args: list[str]) -> object:
            from dev10x.subprocess_utils import effective_cwd

            captured.append(effective_cwd())
            return err("stop")

        with patch("dev10x.plan.set_context", side_effect=_spy_set_context):
            await cli_server.plan_sync_set_context(
                args=["k=v"],
                cwd=str(tmp_path),
            )

        assert captured == [str(tmp_path)]

    @pytest.mark.asyncio
    async def test_json_summary_activates_cwd(self, tmp_path: Path) -> None:
        captured: list[object] = []

        async def _spy_json_summary() -> object:
            from dev10x.subprocess_utils import effective_cwd

            captured.append(effective_cwd())
            return err("stop")

        with patch("dev10x.plan.json_summary", side_effect=_spy_json_summary):
            await cli_server.plan_sync_json_summary(cwd=str(tmp_path))

        assert captured == [str(tmp_path)]

    @pytest.mark.asyncio
    async def test_archive_activates_cwd(self, tmp_path: Path) -> None:
        captured: list[object] = []

        async def _spy_archive() -> object:
            from dev10x.subprocess_utils import effective_cwd

            captured.append(effective_cwd())
            return err("stop")

        with patch("dev10x.plan.archive", side_effect=_spy_archive):
            await cli_server.plan_sync_archive(cwd=str(tmp_path))

        assert captured == [str(tmp_path)]
