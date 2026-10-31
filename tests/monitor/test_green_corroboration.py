"""A partial green is not a green while a run for the head is going (GH-1679)."""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest
from dev10x.skills.monitor.ci_check_status import SOURCE_GH_CLI, ChecksRead, compute_verdict

_impl = sys.modules[compute_verdict.__module__]

_HEAD = '{"headRefName": "feat", "headRefOid": "abc123"}'


class _Completed:
    def __init__(self, *, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _run(name: str, status: str, *, head_sha: str = "abc123") -> dict[str, Any]:
    return {"name": name, "status": status, "conclusion": None, "head_sha": head_sha}


def _serve_gh(
    monkeypatch: pytest.MonkeyPatch,
    *,
    head: tuple[int, str] = (0, _HEAD),
    runs: tuple[int, str] = (0, '{"workflow_runs": []}'),
) -> None:
    def _fake(cmd: list[str], **_kwargs: Any) -> _Completed:
        returncode, stdout = head if cmd[:3] == ["gh", "pr", "view"] else runs
        return _Completed(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(_impl.subprocess, "run", _fake)


def _runs_payload(*runs: dict[str, Any]) -> tuple[int, str]:
    return 0, json.dumps({"workflow_runs": list(runs)})


def _serve_checks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    checks: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(
        _impl,
        "get_annotated_checks",
        lambda **_k: ChecksRead(checks=checks, source=SOURCE_GH_CLI),
    )
    monkeypatch.setattr(_impl, "get_pr_state", lambda **_k: _impl.PrState(mergeable="MERGEABLE"))


_PARTIAL_GREEN = [{"name": "lint", "bucket": "pass", "required": False}]


class TestRunsRunningAtHead:
    def test_lists_unfinished_runs_for_the_head(self, monkeypatch):
        _serve_gh(
            monkeypatch,
            runs=_runs_payload(
                _run("CI Gate", "in_progress"),
                _run("Lint", "completed"),
                _run("Bots", "queued"),
            ),
        )
        assert _impl.runs_running_at_head(pr_number=1, repo="o/r") == ["Bots", "CI Gate"]

    def test_runs_for_another_head_do_not_count(self, monkeypatch):
        _serve_gh(monkeypatch, runs=_runs_payload(_run("CI Gate", "in_progress", head_sha="old")))
        assert _impl.runs_running_at_head(pr_number=1, repo="o/r") == []

    def test_unnamed_run_is_reported_as_unknown(self, monkeypatch):
        _serve_gh(monkeypatch, runs=_runs_payload({"status": "queued", "head_sha": "abc123"}))
        assert _impl.runs_running_at_head(pr_number=1, repo="o/r") == ["unknown"]

    @pytest.mark.parametrize(
        ("head", "runs"),
        [((1, ""), (0, '{"workflow_runs": []}')), ((0, _HEAD), (1, ""))],
        ids=["head-unreadable", "runs-unreadable"],
    )
    def test_an_unreadable_source_is_none(self, monkeypatch, head, runs):
        _serve_gh(monkeypatch, head=head, runs=runs)
        assert _impl.runs_running_at_head(pr_number=1, repo="o/r") is None

    def test_a_timed_out_read_is_none(self, monkeypatch):
        def _timeout(cmd: list[str], **_kwargs: Any) -> _Completed:
            raise _impl.subprocess.TimeoutExpired(cmd=cmd, timeout=30)

        monkeypatch.setattr(_impl.subprocess, "run", _timeout)
        assert _impl.runs_running_at_head(pr_number=1, repo="o/r") is None


class TestProbeCorroboratesGreen:
    @pytest.fixture
    def overturned(self, monkeypatch) -> dict:
        _serve_checks(monkeypatch, checks=_PARTIAL_GREEN)
        monkeypatch.setattr(_impl, "runs_running_at_head", lambda **_k: ["CI Gate"])
        return _impl.probe_once(pr_number=1, repo="o/r")

    def test_a_running_head_run_turns_green_into_pending(self, overturned: dict):
        assert overturned["verdict"] == "pending"

    def test_the_overturn_names_its_source(self, overturned: dict):
        assert overturned["checks_source"] == _impl.SOURCE_RUNS_API_PENDING

    def test_the_overturn_names_the_running_runs(self, overturned: dict):
        assert overturned["running_runs"] == ["CI Gate"]

    def test_a_finished_head_keeps_its_green(self, monkeypatch):
        _serve_checks(monkeypatch, checks=_PARTIAL_GREEN)
        monkeypatch.setattr(_impl, "runs_running_at_head", lambda **_k: [])
        result = _impl.probe_once(pr_number=1, repo="o/r")
        assert result["verdict"] == "green"
        assert result["checks_source"] == SOURCE_GH_CLI

    def test_an_unreadable_cross_check_leaves_green_standing(self, monkeypatch, capsys):
        _serve_checks(monkeypatch, checks=_PARTIAL_GREEN)
        monkeypatch.setattr(_impl, "runs_running_at_head", lambda **_k: None)
        result = _impl.probe_once(pr_number=1, repo="o/r")
        assert result["verdict"] == "green"
        assert "uncorroborated" in capsys.readouterr().err

    def test_a_non_green_verdict_pays_nothing_extra(self, monkeypatch):
        _serve_checks(monkeypatch, checks=[{"name": "lint", "bucket": "pending"}])
        monkeypatch.setattr(_impl, "runs_running_at_head", pytest.fail)
        assert _impl.probe_once(pr_number=1, repo="o/r")["verdict"] == "pending"

    def test_required_only_reads_are_exempt(self, monkeypatch):
        _serve_checks(monkeypatch, checks=_PARTIAL_GREEN)
        monkeypatch.setattr(_impl, "runs_running_at_head", pytest.fail)
        result = _impl.probe_once(pr_number=1, repo="o/r", required_only=True)
        assert result["verdict"] == "green"


class TestWaitForHoldsTheFastPath:
    """The GH-1679 run: green on the first probe, named legs never listed."""

    @pytest.fixture
    def waited(self, monkeypatch) -> tuple[dict, list[float]]:
        slept: list[float] = []
        monkeypatch.setattr(_impl.time, "sleep", slept.append)
        _serve_checks(monkeypatch, checks=_PARTIAL_GREEN)
        monkeypatch.setattr(_impl, "runs_running_at_head", lambda **_k: [])
        result = _impl.poll_until_terminal(
            pr_number=1,
            repo="o/r",
            initial_wait=60,
            poll_interval=30,
            max_polls=2,
            wait_for=["floors", "hook-tests"],
        )
        return result, slept

    def test_an_unregistered_named_leg_keeps_the_wait_alive(self, waited):
        _, slept = waited
        assert slept[0] == 60

    def test_the_unregistered_legs_are_reported(self, waited):
        result, _ = waited
        assert result["unregistered"] == ["floors", "hook-tests"]

    def test_a_budget_ended_with_unregistered_legs_is_not_green(self, waited):
        result, _ = waited
        assert result["verdict"] == "pending"

    def test_a_settled_fast_path_reports_no_unregistered_legs(self, monkeypatch):
        _serve_checks(monkeypatch, checks=_PARTIAL_GREEN)
        monkeypatch.setattr(_impl, "runs_running_at_head", lambda **_k: [])
        result = _impl.poll_until_terminal(pr_number=1, repo="o/r", wait_for=["lint"])
        assert result["unregistered"] == []

    def test_without_wait_for_no_report_is_added(self, monkeypatch):
        _serve_checks(monkeypatch, checks=_PARTIAL_GREEN)
        monkeypatch.setattr(_impl, "runs_running_at_head", lambda **_k: [])
        assert "unregistered" not in _impl.poll_until_terminal(pr_number=1, repo="o/r")
