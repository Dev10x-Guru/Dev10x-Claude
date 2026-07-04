from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import SuccessResult, err, ok

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")


class TestMilestonesBulkCreate:
    @pytest.mark.asyncio
    @patch.object(gh, "milestone_create", new_callable=AsyncMock)
    async def test_creates_all_when_each_succeeds(self, mock_create: AsyncMock) -> None:
        mock_create.side_effect = [
            ok({"number": 1, "title": "M1", "url": "u1"}),
            ok({"number": 2, "title": "M2", "url": "u2"}),
        ]

        result = await gh.milestones_bulk_create(
            milestones=[{"title": "M1"}, {"title": "M2", "description": "d"}],
        )

        assert isinstance(result, SuccessResult)
        assert len(result.value["created"]) == 2
        assert result.value["failed"] == []
        assert mock_create.call_count == 2

    @pytest.mark.asyncio
    @patch.object(gh, "milestone_create", new_callable=AsyncMock)
    async def test_collects_per_entry_failures(self, mock_create: AsyncMock) -> None:
        mock_create.side_effect = [
            ok({"number": 1, "title": "M1", "url": "u1"}),
            err("already exists"),
        ]

        result = await gh.milestones_bulk_create(
            milestones=[{"title": "M1"}, {"title": "M2"}],
        )

        assert len(result.value["created"]) == 1
        assert result.value["failed"] == [{"title": "M2", "error": "already exists"}]

    @pytest.mark.asyncio
    async def test_rejects_empty_input(self) -> None:
        result = await gh.milestones_bulk_create(milestones=[])
        assert result.error == "milestones_bulk_create requires at least one milestone"

    @pytest.mark.asyncio
    @patch.object(gh, "milestone_create", new_callable=AsyncMock)
    async def test_records_missing_title_as_failure(self, mock_create: AsyncMock) -> None:
        result = await gh.milestones_bulk_create(milestones=[{}])
        assert result.value["created"] == []
        assert result.value["failed"][0]["error"] == "missing title"
        mock_create.assert_not_called()


class TestIssuesBulkCreate:
    @pytest.mark.asyncio
    @patch.object(gh, "issue_create", new_callable=AsyncMock)
    async def test_creates_all_when_each_succeeds(self, mock_create: AsyncMock) -> None:
        mock_create.side_effect = [
            ok({"number": 100, "url": "u1"}),
            ok({"number": 101, "url": "u2", "title": "I2"}),
        ]

        result = await gh.issues_bulk_create(
            issues=[
                {"title": "I1", "labels": ["bug"]},
                {"title": "I2", "milestone": "M1", "body": "details"},
            ],
        )

        assert len(result.value["created"]) == 2
        # title is back-filled when the underlying tool omits it
        assert result.value["created"][0]["title"] == "I1"
        assert result.value["created"][1]["title"] == "I2"

    @pytest.mark.asyncio
    @patch.object(gh, "issue_create", new_callable=AsyncMock)
    async def test_collects_per_entry_failures(self, mock_create: AsyncMock) -> None:
        mock_create.side_effect = [
            err("milestone not found"),
            ok({"number": 5, "url": "u"}),
        ]

        result = await gh.issues_bulk_create(
            issues=[{"title": "I1"}, {"title": "I2"}],
        )

        assert len(result.value["created"]) == 1
        assert result.value["failed"] == [{"title": "I1", "error": "milestone not found"}]

    @pytest.mark.asyncio
    async def test_rejects_empty_input(self) -> None:
        result = await gh.issues_bulk_create(issues=[])
        assert result.error == "issues_bulk_create requires at least one issue"

    @pytest.mark.asyncio
    @patch.object(gh, "issue_create", new_callable=AsyncMock)
    async def test_records_missing_title_as_failure(self, mock_create: AsyncMock) -> None:
        result = await gh.issues_bulk_create(issues=[{}])
        assert result.value["created"] == []
        assert result.value["failed"][0]["error"] == "missing title"
        mock_create.assert_not_called()


class TestIssuesBulkEdit:
    @pytest.mark.asyncio
    @patch.object(gh, "issue_edit", new_callable=AsyncMock)
    async def test_edits_all_when_each_succeeds(self, mock_edit: AsyncMock) -> None:
        mock_edit.side_effect = [
            ok({"number": 10, "url": "u10"}),
            ok({"number": 11, "url": "u11"}),
        ]

        result = await gh.issues_bulk_edit(
            edits=[
                {"number": 10, "milestone": "M2"},
                {"number": 11, "labels": ["wontfix"]},
            ],
        )

        assert len(result.value["edited"]) == 2
        assert result.value["failed"] == []

    @pytest.mark.asyncio
    @patch.object(gh, "issue_edit", new_callable=AsyncMock)
    async def test_collects_per_entry_failures(self, mock_edit: AsyncMock) -> None:
        mock_edit.side_effect = [
            err("issue locked"),
            ok({"number": 11, "url": "u11"}),
        ]

        result = await gh.issues_bulk_edit(
            edits=[{"number": 10, "title": "new"}, {"number": 11, "body": "x"}],
        )

        assert len(result.value["edited"]) == 1
        assert result.value["failed"] == [{"number": 10, "error": "issue locked"}]

    @pytest.mark.asyncio
    @patch.object(gh, "issue_edit", new_callable=AsyncMock)
    async def test_records_missing_number_as_failure(self, mock_edit: AsyncMock) -> None:
        result = await gh.issues_bulk_edit(edits=[{"title": "x"}])
        assert result.value["edited"] == []
        assert result.value["failed"][0]["error"] == "missing or non-integer number"
        mock_edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_empty_input(self) -> None:
        result = await gh.issues_bulk_edit(edits=[])
        assert result.error == "issues_bulk_edit requires at least one edit"
