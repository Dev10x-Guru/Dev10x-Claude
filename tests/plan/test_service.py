from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.plan.service import (
    PlanServiceError,
    archive_plan,
    plan_summary,
    set_plan_context,
)

SERVICE = "dev10x.plan.service"


class TestSetPlanContext:
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    def test_raises_outside_git_repo(self, _toplevel: object) -> None:
        with pytest.raises(PlanServiceError, match="git repository"):
            set_plan_context(args=["k=v"])

    def test_raises_for_invalid_arg(self, tmp_path: Path) -> None:
        with patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)):
            with pytest.raises(PlanServiceError, match="K=V"):
                set_plan_context(args=["no-equals"])

    def test_returns_updated_keys(self, tmp_path: Path) -> None:
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="b"),
        ):
            updated = set_plan_context(args=["work_type=feature", 'tickets=["X"]'])

        assert "work_type" in updated
        assert "tickets" in updated


class TestPlanSummary:
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    def test_raises_outside_git_repo(self, _toplevel: object) -> None:
        with pytest.raises(PlanServiceError):
            plan_summary()

    def test_returns_empty_when_no_plan(self, tmp_path: Path) -> None:
        with patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)):
            assert plan_summary() == {}

    def test_returns_dict_when_plan_exists(self, tmp_path: Path) -> None:
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="b"),
        ):
            set_plan_context(args=["work_type=feature"])
            result = plan_summary()

        assert result["plan"]["context"]["work_type"] == "feature"


class TestArchivePlan:
    @patch(f"{SERVICE}.get_toplevel", return_value=None)
    def test_raises_outside_git_repo(self, _toplevel: object) -> None:
        with pytest.raises(PlanServiceError):
            archive_plan()

    def test_returns_archived_false_when_missing(self, tmp_path: Path) -> None:
        with patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)):
            assert archive_plan() == {"archived": False}

    def test_archives_existing_plan(self, tmp_path: Path) -> None:
        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="feature/x"),
        ):
            set_plan_context(args=["work_type=feature"])
            result = archive_plan()

        assert result["archived"] is True
        assert result["archive_name"].startswith("plan-")
        assert result["archive_name"].endswith(".yaml")
        archive_dir = tmp_path / ".claude" / "session" / "archive"
        assert (archive_dir / result["archive_name"]).exists()
        # Active plan is moved away
        assert not (tmp_path / ".claude" / "session" / "plan.yaml").exists()


class TestSetPlanContextHoldsLock:
    """E3: set_plan_context must serialize load→mutate→save via file_lock."""

    def test_holds_file_lock_around_cycle(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch("dev10x.domain.documents.plan._get_branch", return_value="b"),
            patch(f"{SERVICE}.file_lock") as mock_lock,
        ):
            mock_lock.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
            set_plan_context(args=["work_type=feature"])

        mock_lock.assert_called_once()
        plan_path = tmp_path / ".claude" / "session" / "plan.yaml"
        assert mock_lock.call_args.args[0] == plan_path


class TestArchivePlanHoldsLock:
    def test_holds_file_lock_around_cycle(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        with (
            patch(f"{SERVICE}.get_toplevel", return_value=str(tmp_path)),
            patch(f"{SERVICE}.file_lock") as mock_lock,
        ):
            mock_lock.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
            archive_plan()

        mock_lock.assert_called_once()
