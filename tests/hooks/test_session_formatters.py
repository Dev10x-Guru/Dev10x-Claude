from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dev10x.hooks.session import (
    _format_decision_guidance,
    _format_plan_summary,
    _format_session_state,
    _read_friction_level,
)


class TestFormatSessionState:
    @pytest.fixture()
    def state(self) -> dict:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "branch": "janusz/GH-100/fix-bug",
            "worktree": "dev10x-ai-2",
            "session_id": "abc-123",
            "modified_files": ["src/app.py"],
            "staged_files": [],
            "recent_commits": ["abc1234 Fix the bug"],
        }

    def test_includes_branch(self, state: dict) -> None:
        result = _format_session_state(state=state)
        assert "janusz/GH-100/fix-bug" in result

    def test_includes_worktree(self, state: dict) -> None:
        result = _format_session_state(state=state)
        assert "dev10x-ai-2" in result

    def test_includes_session_id(self, state: dict) -> None:
        result = _format_session_state(state=state)
        assert "abc-123" in result

    def test_includes_modified_files(self, state: dict) -> None:
        result = _format_session_state(state=state)
        assert "src/app.py" in result

    def test_includes_resume_command(self, state: dict) -> None:
        result = _format_session_state(state=state)
        assert "claude --resume abc-123" in result

    def test_marks_stale_sessions(self) -> None:
        old_time = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
        state = {"timestamp": old_time, "branch": "b", "session_id": "s"}
        result = _format_session_state(state=state)
        assert "STALE" in result

    def test_returns_empty_without_timestamp(self) -> None:
        result = _format_session_state(state={"branch": "b"})
        assert result == ""

    def test_omits_worktree_when_empty(self) -> None:
        state = {
            "timestamp": datetime.now(UTC).isoformat(),
            "branch": "main",
            "worktree": "",
            "session_id": "s",
        }
        result = _format_session_state(state=state)
        assert "Worktree" not in result


class TestFormatPlanSummary:
    @pytest.fixture()
    def plan(self) -> dict:
        return {
            "plan": {
                "status": "in_progress",
                "branch": "janusz/GH-50/feature",
                "last_synced": "2026-04-10T12:00:00Z",
                "context": {
                    "work_type": "feature",
                    "tickets": ["GH-50"],
                },
            },
            "tasks": [
                {"id": "1", "subject": "Set up workspace", "status": "completed"},
                {"id": "2", "subject": "Implement", "status": "in_progress"},
                {"id": "3", "subject": "Test", "status": "pending"},
            ],
        }

    def test_includes_task_counts(self, plan: dict) -> None:
        result = _format_plan_summary(plan=plan)
        assert "1/3 tasks completed" in result

    def test_includes_plan_branch(self, plan: dict) -> None:
        result = _format_plan_summary(plan=plan)
        assert "janusz/GH-50/feature" in result

    def test_includes_pending_tasks(self, plan: dict) -> None:
        result = _format_plan_summary(plan=plan)
        assert "Implement" in result
        assert "Test" in result

    def test_excludes_completed_from_remaining(self, plan: dict) -> None:
        result = _format_plan_summary(plan=plan)
        lines = [line for line in result.splitlines() if "Set up workspace" in line]
        assert not lines

    def test_includes_work_type(self, plan: dict) -> None:
        result = _format_plan_summary(plan=plan)
        assert "feature" in result

    def test_includes_tickets(self, plan: dict) -> None:
        result = _format_plan_summary(plan=plan)
        assert "GH-50" in result

    def test_shows_archive_hint_when_completed(self) -> None:
        plan = {
            "plan": {"status": "completed", "branch": "b", "last_synced": "t"},
            "tasks": [],
        }
        result = _format_plan_summary(plan=plan)
        assert "archived" in result.lower()

    def test_handles_empty_plan(self) -> None:
        result = _format_plan_summary(plan={})
        assert "0/0 tasks completed" in result

    def test_includes_pending_decisions(self) -> None:
        plan = {
            "plan": {"status": "in_progress", "branch": "b", "last_synced": "t"},
            "tasks": [
                {
                    "id": "1",
                    "subject": "Choose approach",
                    "status": "pending",
                    "metadata": {
                        "decision_needed": "Fix strategy",
                        "options": ["retry", "timeout"],
                    },
                },
            ],
        }

        result = _format_plan_summary(plan=plan)

        assert "Pending decisions" in result
        assert "Fix strategy" in result


class TestReadFrictionLevel:
    def test_reads_friction_level_from_yaml(self, tmp_path: Path) -> None:
        session_dir = tmp_path / ".claude" / "Dev10x"
        session_dir.mkdir(parents=True)
        (session_dir / "session.yaml").write_text("friction_level: adaptive\n")

        result = _read_friction_level(toplevel=str(tmp_path))

        assert result == "adaptive"

    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        result = _read_friction_level(toplevel=str(tmp_path))

        assert result == ""

    def test_returns_empty_for_invalid_yaml(self, tmp_path: Path) -> None:
        session_dir = tmp_path / ".claude" / "Dev10x"
        session_dir.mkdir(parents=True)
        (session_dir / "session.yaml").write_text(": invalid: yaml: [")

        result = _read_friction_level(toplevel=str(tmp_path))

        assert result == ""

    def test_returns_empty_when_key_missing(self, tmp_path: Path) -> None:
        session_dir = tmp_path / ".claude" / "Dev10x"
        session_dir.mkdir(parents=True)
        (session_dir / "session.yaml").write_text("active_modes: []\n")

        result = _read_friction_level(toplevel=str(tmp_path))

        assert result == ""


class TestFormatDecisionGuidance:
    @pytest.fixture()
    def plan_with_decision(self) -> dict:
        return {
            "plan": {"status": "in_progress"},
            "tasks": [
                {
                    "id": "1",
                    "subject": "Choose approach",
                    "status": "pending",
                    "metadata": {
                        "decision_needed": "Fix strategy",
                        "options": ["retry", "timeout"],
                    },
                },
                {"id": "2", "subject": "Implement", "status": "pending"},
            ],
        }

    @pytest.fixture()
    def plan_without_decision(self) -> dict:
        return {
            "plan": {"status": "in_progress"},
            "tasks": [
                {"id": "1", "subject": "Implement", "status": "pending"},
            ],
        }

    def test_adaptive_auto_selects_decisions(
        self,
        plan_with_decision: dict,
    ) -> None:
        result = _format_decision_guidance(
            plan=plan_with_decision,
            friction_level="adaptive",
        )

        assert "auto-select" in result
        assert "without calling AskUserQuestion" in result

    def test_guided_re_asks_decisions(
        self,
        plan_with_decision: dict,
    ) -> None:
        result = _format_decision_guidance(
            plan=plan_with_decision,
            friction_level="guided",
        )

        assert "AskUserQuestion" in result

    def test_strict_re_asks_decisions(
        self,
        plan_with_decision: dict,
    ) -> None:
        result = _format_decision_guidance(
            plan=plan_with_decision,
            friction_level="strict",
        )

        assert "AskUserQuestion" in result

    def test_no_decisions_with_remaining_tasks(
        self,
        plan_without_decision: dict,
    ) -> None:
        result = _format_decision_guidance(
            plan=plan_without_decision,
            friction_level="guided",
        )

        assert "Auto-advance" in result

    def test_no_decisions_all_completed(self) -> None:
        plan: dict = {
            "plan": {"status": "completed"},
            "tasks": [
                {"id": "1", "subject": "Done", "status": "completed"},
            ],
        }

        result = _format_decision_guidance(
            plan=plan,
            friction_level="guided",
        )

        assert result == ""

    def test_empty_friction_level_re_asks(
        self,
        plan_with_decision: dict,
    ) -> None:
        result = _format_decision_guidance(
            plan=plan_with_decision,
            friction_level="",
        )

        assert "AskUserQuestion" in result
