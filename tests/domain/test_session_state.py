from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dev10x.domain.documents.session_state import PlanContext, PlanSummary, SessionState


class TestSessionStateFormatForDisplay:
    def test_returns_empty_for_no_timestamp(self) -> None:
        state = SessionState()

        assert state.format_for_display() == ""

    def test_includes_branch_and_session_id(self) -> None:
        state = SessionState(
            timestamp=datetime.now(UTC).isoformat(),
            branch="feature/test",
            session_id="abc-123",
        )

        result = state.format_for_display()

        assert "feature/test" in result
        assert "abc-123" in result

    def test_includes_worktree_when_set(self) -> None:
        state = SessionState(
            timestamp=datetime.now(UTC).isoformat(),
            worktree="dev10x-ai-1",
        )

        result = state.format_for_display()

        assert "Worktree: dev10x-ai-1" in result

    def test_shows_modified_files(self) -> None:
        state = SessionState(
            timestamp=datetime.now(UTC).isoformat(),
            modified_files=["src/main.py", "tests/test_main.py"],
        )

        result = state.format_for_display()

        assert "- src/main.py" in result

    def test_shows_none_for_empty_files(self) -> None:
        state = SessionState(
            timestamp=datetime.now(UTC).isoformat(),
        )

        result = state.format_for_display()

        assert "Modified files:\nnone" in result

    def test_marks_stale_sessions(self) -> None:
        state = SessionState(timestamp="2020-01-01T00:00:00+00:00")

        result = state.format_for_display()

        assert "STALE" in result

    def test_handles_invalid_timestamp(self) -> None:
        state = SessionState(timestamp="not-a-date")

        result = state.format_for_display()

        assert "Prior session state" in result


class TestSessionStateFromDict:
    def test_parses_all_fields(self) -> None:
        data = {
            "timestamp": "2026-01-01T00:00:00Z",
            "branch": "main",
            "worktree": "wt1",
            "session_id": "sid",
            "modified_files": ["a.py"],
            "staged_files": ["b.py"],
            "recent_commits": ["abc Fix"],
        }

        state = SessionState.from_dict(data=data)

        assert state.branch == "main"
        assert state.worktree == "wt1"
        assert state.modified_files == ["a.py"]

    def test_defaults_for_missing_fields(self) -> None:
        state = SessionState.from_dict(data={})

        assert state.branch == "unknown"
        assert state.modified_files == []


class TestPlanContextFromDict:
    def test_parses_all_fields(self) -> None:
        ctx = PlanContext.from_dict(
            data={
                "work_type": "feature",
                "tickets": ["GH-1", "GH-2"],
                "routing_table": {"commit": "Skill(Dev10x:git-commit)"},
                "gathered_summary": "Summary here",
            }
        )

        assert ctx.work_type == "feature"
        assert ctx.tickets == ["GH-1", "GH-2"]
        assert ctx.routing_table["commit"] == "Skill(Dev10x:git-commit)"

    def test_wraps_string_tickets_in_list(self) -> None:
        ctx = PlanContext.from_dict(data={"tickets": "GH-1"})

        assert ctx.tickets == ["GH-1"]


class TestPlanSummaryFormatForDisplay:
    @pytest.fixture()
    def summary(self) -> PlanSummary:
        return PlanSummary(
            status="in_progress",
            branch="feature/test",
            last_synced="2026-01-01",
            context=PlanContext(
                work_type="feature",
                tickets=["GH-1"],
                routing_table={"commit": "Skill(Dev10x:git-commit)"},
            ),
            tasks=[
                {"id": "1", "subject": "Task A", "status": "completed"},
                {"id": "2", "subject": "Task B", "status": "pending"},
            ],
        )

    def test_includes_completion_count(self, summary: PlanSummary) -> None:
        result = summary.format_for_display()

        assert "1/2 tasks completed" in result

    def test_includes_pending_tasks(self, summary: PlanSummary) -> None:
        result = summary.format_for_display()

        assert "Task B" in result
        assert "Task A" not in result.split("Remaining")[1]

    def test_includes_work_type(self, summary: PlanSummary) -> None:
        assert "Work type: feature" in summary.format_for_display()

    def test_includes_tickets(self, summary: PlanSummary) -> None:
        assert "Tickets: GH-1" in summary.format_for_display()

    def test_includes_routing(self, summary: PlanSummary) -> None:
        assert "Skill routing" in summary.format_for_display()

    def test_shows_archive_message_when_completed(self) -> None:
        summary = PlanSummary(status="completed")

        assert "can be archived" in summary.format_for_display()


class TestPlanSummaryPendingTasks:
    def test_excludes_completed_and_deleted(self) -> None:
        summary = PlanSummary(
            tasks=[
                {"id": "1", "subject": "A", "status": "pending"},
                {"id": "2", "subject": "B", "status": "in_progress"},
                {"id": "3", "subject": "C", "status": "completed"},
                {"id": "4", "subject": "D", "status": "deleted"},
            ],
        )

        ids = [t.id for t in summary.pending_tasks]

        assert ids == ["1", "2"]

    def test_empty_when_no_tasks(self) -> None:
        assert PlanSummary().pending_tasks == []


class TestPlanSummaryHasRemainingTasks:
    def test_true_when_pending_present(self) -> None:
        summary = PlanSummary(
            tasks=[
                {"id": "1", "subject": "A", "status": "pending"},
                {"id": "2", "subject": "B", "status": "completed"},
            ],
        )

        assert summary.has_remaining_tasks is True

    def test_false_when_all_completed_or_deleted(self) -> None:
        summary = PlanSummary(
            tasks=[
                {"id": "1", "subject": "A", "status": "completed"},
                {"id": "2", "subject": "B", "status": "deleted"},
            ],
        )

        assert summary.has_remaining_tasks is False

    def test_false_when_no_tasks(self) -> None:
        assert PlanSummary().has_remaining_tasks is False


class TestPlanSummaryPendingDecisions:
    def test_returns_tasks_with_decision_needed(self) -> None:
        summary = PlanSummary(
            tasks=[
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
        )

        result = summary.pending_decisions

        assert len(result) == 1
        assert result[0].id == "1"

    def test_excludes_completed_tasks(self) -> None:
        summary = PlanSummary(
            tasks=[
                {
                    "id": "1",
                    "subject": "Done decision",
                    "status": "completed",
                    "metadata": {"decision_needed": "Already answered"},
                },
            ],
        )

        assert summary.pending_decisions == []

    def test_excludes_deleted_tasks(self) -> None:
        summary = PlanSummary(
            tasks=[
                {
                    "id": "1",
                    "subject": "Deleted",
                    "status": "deleted",
                    "metadata": {"decision_needed": "Removed"},
                },
            ],
        )

        assert summary.pending_decisions == []

    def test_returns_empty_when_no_decisions(self) -> None:
        summary = PlanSummary(
            tasks=[
                {"id": "1", "subject": "Regular task", "status": "pending"},
            ],
        )

        assert summary.pending_decisions == []


class TestPlanSummaryDisplayWithDecisions:
    def test_includes_pending_decisions_section(self) -> None:
        summary = PlanSummary(
            status="in_progress",
            tasks=[
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
        )

        result = summary.format_for_display()

        assert "Pending decisions" in result
        assert "Fix strategy" in result
        assert "retry" in result

    def test_omits_decisions_section_when_none(self) -> None:
        summary = PlanSummary(
            tasks=[{"id": "1", "subject": "Task", "status": "pending"}],
        )

        result = summary.format_for_display()

        assert "Pending decisions" not in result


class TestPlanSummaryCompactionWithDecisions:
    def test_marks_decision_needed_inline(self) -> None:
        summary = PlanSummary(
            tasks=[
                {
                    "id": "1",
                    "subject": "Choose",
                    "status": "pending",
                    "metadata": {"decision_needed": "Strategy choice"},
                },
            ],
        )

        result = summary.format_for_compaction()

        assert "DECISION NEEDED" in result
        assert "Strategy choice" in result

    def test_includes_pending_decisions_section(self) -> None:
        summary = PlanSummary(
            tasks=[
                {
                    "id": "1",
                    "subject": "Choose",
                    "status": "pending",
                    "metadata": {
                        "decision_needed": "Strategy",
                        "options": ["A", "B"],
                    },
                },
            ],
        )

        result = summary.format_for_compaction()

        assert "Pending Decisions" in result


class TestPlanSummaryFormatForCompaction:
    def test_includes_task_metadata(self) -> None:
        summary = PlanSummary(
            tasks=[
                {
                    "id": "1",
                    "subject": "Implement",
                    "status": "pending",
                    "metadata": {"type": "epic", "skills": ["test"]},
                },
            ],
        )

        result = summary.format_for_compaction()

        assert "(epic)" in result
        assert "→ test" in result

    def test_includes_routing_table(self) -> None:
        summary = PlanSummary(
            context=PlanContext(
                routing_table={"push": "Skill(Dev10x:git)"},
            ),
        )

        result = summary.format_for_compaction()

        assert "Skill Routing Table" in result
        assert "push → Skill(Dev10x:git)" in result

    def test_includes_gathered_summary(self) -> None:
        summary = PlanSummary(
            context=PlanContext(gathered_summary="Bug in payments"),
        )

        result = summary.format_for_compaction()

        assert "Bug in payments" in result

    def test_includes_plan_state_header(self) -> None:
        result = PlanSummary().format_for_compaction()

        assert result.startswith("## Persisted Plan State")
