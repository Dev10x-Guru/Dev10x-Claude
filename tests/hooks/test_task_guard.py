"""Tests for the empty-task-list guard (GH-681 / GH-149, GH-1556/GH-1557)."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.documents.plan import Plan
from dev10x.domain.events.hook_input import HookResult

from dev10x.hooks import task_guard as legacy_tg
from dev10x.tasks.hooks import task_guard as tg

CODING = frozenset({"coding"})
NONE: frozenset[str] = frozenset()
WORK_ON = {"work_on": "work-on"}


def _plan(tasks: list[dict], *, context: dict[str, Any] | None = None) -> Plan:
    metadata = {"context": WORK_ON if context is None else context}
    return Plan(metadata=metadata, tasks=tasks)


VERIFY = {"id": "9", "subject": "Verify acceptance criteria", "status": "pending"}
OPEN_A = {"id": "1", "subject": "Implement fix", "status": "in_progress"}
DONE_B = {"id": "2", "subject": "Set up workspace", "status": "completed"}


class TestModuleHome:
    def test_old_path_is_the_tasks_module(self) -> None:
        assert legacy_tg is tg


class TestIsGuardedPlan:
    @pytest.mark.parametrize(
        ("context", "enabled", "expected"),
        [
            pytest.param({"guard_terminal_task": True}, NONE, True, id="generic-flag"),
            pytest.param({"guard_terminal_task": False}, CODING, False, id="flag-off"),
            pytest.param(WORK_ON, CODING, True, id="work-on-coding-on"),
            pytest.param({"routing_table": []}, CODING, True, id="routing-table-coding-on"),
            pytest.param(WORK_ON, NONE, False, id="work-on-coding-off"),
            pytest.param({}, CODING, False, id="ad-hoc"),
            pytest.param("not-a-mapping", CODING, False, id="malformed-context"),
        ],
    )
    def test_scope(self, context: Any, enabled: frozenset[str], expected: bool) -> None:
        plan = Plan(metadata={"context": context}, tasks=[VERIFY])
        assert tg.is_guarded_plan(plan=plan, enabled_plugins=enabled) is expected


class TestEnabledTriggerPlugins:
    @pytest.mark.parametrize(
        ("enabled", "expected"),
        [(True, CODING), (False, NONE)],
    )
    def test_reports_enabled_trigger_plugins(
        self,
        monkeypatch: pytest.MonkeyPatch,
        enabled: bool,
        expected: frozenset[str],
    ) -> None:
        monkeypatch.setattr(tg, "is_plugin_enabled", lambda *, key, project_dir: enabled)
        assert tg.enabled_trigger_plugins(project_dir=Path("/repo")) == expected


class TestGuardDecisionAllows:
    def test_non_closing_status_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "in_progress"},
            plan=_plan([VERIFY]),
            enabled_plugins=CODING,
        )
        assert decision is None

    def test_missing_task_id_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"status": "completed"},
            plan=_plan([VERIFY]),
            enabled_plugins=CODING,
        )
        assert decision is None

    def test_non_work_on_plan_allows_even_when_last(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([VERIFY], context={}),
            enabled_plugins=CODING,
        )
        assert decision is None

    def test_work_on_plan_allows_when_coding_disabled(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([VERIFY]),
            enabled_plugins=NONE,
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
            enabled_plugins=CODING,
        )
        assert decision is None

    def test_env_kill_switch_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_TASK_GUARD_OFF", "1")
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([VERIFY]),
            enabled_plugins=CODING,
        )
        assert decision is None

    def test_unknown_task_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "404", "status": "completed"},
            plan=_plan([VERIFY]),
            enabled_plugins=CODING,
        )
        assert decision is None

    def test_already_closed_task_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "2", "status": "completed"},
            plan=_plan([VERIFY, DONE_B]),
            enabled_plugins=CODING,
        )
        assert decision is None

    def test_non_terminal_task_with_open_siblings_allows(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "1", "status": "completed"},
            plan=_plan([OPEN_A, VERIFY]),
            enabled_plugins=CODING,
        )
        assert decision is None


class TestGuardDecisionBlocks:
    def test_last_open_task_completed_blocks(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "1", "status": "completed"},
            plan=_plan([OPEN_A, DONE_B]),
            enabled_plugins=CODING,
        )
        assert isinstance(decision, HookResult)
        assert "GH-149" in decision.message
        assert "supervisor_confirmed" in decision.message

    def test_last_open_task_deleted_blocks(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "1", "status": "deleted"},
            plan=_plan([OPEN_A]),
            enabled_plugins=CODING,
        )
        assert isinstance(decision, HookResult)
        assert "last open task" in decision.message

    def test_terminal_task_with_open_siblings_blocks(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([OPEN_A, VERIFY]),
            enabled_plugins=CODING,
        )
        assert isinstance(decision, HookResult)
        assert "terminal Verify-AC task" in decision.message

    def test_generic_flag_blocks_without_coding(self) -> None:
        decision = tg.guard_decision(
            tool_input={"taskId": "9", "status": "completed"},
            plan=_plan([VERIFY], context={"guard_terminal_task": True}),
            enabled_plugins=NONE,
        )
        assert isinstance(decision, HookResult)
        assert "guard_terminal_task" in decision.message


@pytest.fixture
def claude_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "claude-home"
    home.mkdir()
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(home))
    return home


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, claude_home: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(tg, "get_toplevel", lambda: str(root))
    monkeypatch.setattr(tg, "get_plan_path", lambda *, toplevel: root / "plan.yaml")
    return root


def _disable_coding(*, repo: Path) -> None:
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"enabledPlugins": {"dev10x@Dev10x-Guru": False}}))


class TestCmdHook:
    def _run(self, *, monkeypatch: pytest.MonkeyPatch, payload: str) -> int:
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        with pytest.raises(SystemExit) as exc:
            tg.cmd_hook()
        return exc.value.code

    def _close(self, *, task_id: str) -> str:
        return json.dumps(
            {"tool_name": "TaskUpdate", "tool_input": {"taskId": task_id, "status": "completed"}}
        )

    def test_empty_stdin_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._run(monkeypatch=monkeypatch, payload="   ") == 0

    def test_other_tool_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps({"tool_name": "TaskCreate", "tool_input": {}})
        assert self._run(monkeypatch=monkeypatch, payload=payload) == 0

    @pytest.mark.parametrize(
        ("payload", "reason"),
        [
            pytest.param("{not json", "not valid JSON", id="malformed-json"),
            pytest.param("[]", "payload is not a JSON object (list)", id="list"),
            pytest.param("1", "payload is not a JSON object (int)", id="scalar"),
            pytest.param(
                json.dumps({"tool_name": "TaskUpdate", "tool_input": "oops"}),
                "tool_input is not a JSON object (str)",
                id="non-dict-tool-input",
            ),
        ],
    )
    def test_fail_open_allows_and_logs_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        payload: str,
        reason: str,
    ) -> None:
        caplog.set_level(logging.WARNING, logger=tg.__name__)
        assert self._run(monkeypatch=monkeypatch, payload=payload) == 0
        assert reason in caplog.text

    def test_no_toplevel_allows_and_logs_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger=tg.__name__)
        monkeypatch.setattr(tg, "get_toplevel", lambda: None)
        assert self._run(monkeypatch=monkeypatch, payload=self._close(task_id="1")) == 0
        assert "no git toplevel" in caplog.text

    def test_other_tool_logs_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger=tg.__name__)
        self._run(
            monkeypatch=monkeypatch,
            payload=json.dumps({"tool_name": "TaskCreate", "tool_input": {}}),
        )
        assert caplog.text == ""

    def test_block_exits_two(self, monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
        monkeypatch.setattr(tg.Plan, "load", classmethod(lambda cls, *, path: _plan([OPEN_A])))
        assert self._run(monkeypatch=monkeypatch, payload=self._close(task_id="1")) == 2

    def test_coding_disabled_work_on_plan_exits_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        repo: Path,
    ) -> None:
        _disable_coding(repo=repo)
        monkeypatch.setattr(tg.Plan, "load", classmethod(lambda cls, *, path: _plan([OPEN_A])))
        assert self._run(monkeypatch=monkeypatch, payload=self._close(task_id="1")) == 0

    def test_allow_exits_zero(self, monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
        monkeypatch.setattr(
            tg.Plan, "load", classmethod(lambda cls, *, path: _plan([OPEN_A, VERIFY]))
        )
        assert self._run(monkeypatch=monkeypatch, payload=self._close(task_id="1")) == 0
