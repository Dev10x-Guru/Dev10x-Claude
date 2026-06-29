"""Tests for the empty-task-list guard (GH-681 / GH-149)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dev10x.domain.documents.plan import Plan
from dev10x.domain.events.hook_input import HookResult
from dev10x.hooks import task_guard as tg


def _plan(tasks: list[dict], *, work_on: bool = True) -> Plan:
    metadata = {"context": {"work_on": "work-on"}} if work_on else {}
    return Plan(metadata=metadata, tasks=tasks)


VERIFY = {"id": "9", "subject": "Verify acceptance criteria", "status": "pending"}
OPEN_A = {"id": "1", "subject": "Implement fix", "status": "in_progress"}
DONE_B = {"id": "2", "subject": "Set up workspace", "status": "completed"}


class TestGuardDecisionAllows:
    def test_non_closing_status_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "in_progress"},
            plan=_plan([VERIFY]),
        )
        assert decision is None

    def test_missing_task_id_allows(self) -> None:
        decision = tg.guard_decision(tool_input={"status": "completed"}, plan=_plan([VERIFY]))
        assert decision is None

    def test_non_work_on_plan_allows_even_when_last(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([VERIFY], work_on=False),
        )
        assert decision is None

    def test_supervisor_confirmed_override_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={
                "taskId": "9",
                "status": "completed",
                "metadata": {"supervisor_confirmed": True},
            },
            plan=_plan([VERIFY]),
        )
        assert decision is None

    def test_env_kill_switch_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_TASK_GUARD_OFF", "1")
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([VERIFY]),
        )
        assert decision is None

    def test_unknown_task_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "404", "status": "completed"},
            plan=_plan([VERIFY]),
        )
        assert decision is None

    def test_already_closed_task_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "2", "status": "completed"},
            plan=_plan([VERIFY, DONE_B]),
        )
        assert decision is None

    def test_non_terminal_task_with_open_siblings_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "1", "status": "completed"},
            plan=_plan([OPEN_A, VERIFY]),
        )
        assert decision is None


class TestGuardDecisionBlocks:
    def test_last_open_task_completed_blocks(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "1", "status": "completed"},
            plan=_plan([OPEN_A, DONE_B]),
        )
        assert isinstance(decision, HookResult)
        assert "GH-149" in decision.message
        assert "supervisor_confirmed" in decision.message

    def test_last_open_task_deleted_blocks(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "1", "status": "deleted"},
            plan=_plan([OPEN_A]),
        )
        assert isinstance(decision, HookResult)
        assert "last open task" in decision.message

    def test_terminal_task_with_open_siblings_blocks(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([OPEN_A, VERIFY]),
        )
        assert isinstance(decision, HookResult)
        assert "terminal Verify-AC task" in decision.message


class TestCmdHook:
    def _run(self, monkeypatch: pytest.MonkeyPatch, payload: str) -> int:
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        with pytest.raises(SystemExit) as exc:
            tg.cmd_hook()
        return exc.value.code

    def test_empty_stdin_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._run(monkeypatch, "   ") == 0

    def test_invalid_json_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._run(monkeypatch, "{not json") == 0

    def test_other_tool_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps({"tool_name": "TaskCreate", "tool_input": {}})
        assert self._run(monkeypatch, payload) == 0

    def test_non_dict_tool_input_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps({"tool_name": "TaskUpdate", "tool_input": "oops"})
        assert self._run(monkeypatch, payload) == 0

    def test_no_toplevel_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tg, "get_toplevel", lambda: None)
        payload = json.dumps(
            {"tool_name": "TaskUpdate", "tool_input": {"taskId": "1", "status": "completed"}}
        )
        assert self._run(monkeypatch, payload) == 0

    def test_block_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tg, "get_toplevel", lambda: "/repo")
        monkeypatch.setattr(tg, "get_plan_path", lambda *, toplevel: Path("/repo/plan.yaml"))
        monkeypatch.setattr(tg.Plan, "load", classmethod(lambda cls, *, path: _plan([OPEN_A])))
        payload = json.dumps(
            {"tool_name": "TaskUpdate", "tool_input": {"taskId": "1", "status": "completed"}}
        )
        assert self._run(monkeypatch, payload) == 2

    def test_allow_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tg, "get_toplevel", lambda: "/repo")
        monkeypatch.setattr(tg, "get_plan_path", lambda *, toplevel: Path("/repo/plan.yaml"))
        monkeypatch.setattr(
            tg.Plan, "load", classmethod(lambda cls, *, path: _plan([OPEN_A, VERIFY]))
        )
        payload = json.dumps(
            {"tool_name": "TaskUpdate", "tool_input": {"taskId": "1", "status": "completed"}}
        )
        assert self._run(monkeypatch, payload) == 0
