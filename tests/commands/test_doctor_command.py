"""CLI surface of the non-interactive doctor sweep (GH-1321).

Every test stubs the sweep — `dev10x doctor run` never reads the
developer's real settings files under pytest.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from dev10x.commands.doctor import doctor
from dev10x.domain.common.result import err, ok
from dev10x.skills.doctor.strategy import Context


@pytest.fixture(autouse=True)
def stub_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dev10x.commands.doctor.build_context", lambda project_root: Context())
    monkeypatch.setattr("dev10x.commands.doctor.load_doctor_acceptances", tuple)


def stub_run(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr("dev10x.commands.doctor.run_doctor", lambda **_kwargs: ok(payload))


def verdict(*, blocking: int = 0) -> dict[str, Any]:
    return {
        "findings": [],
        "accepted": [],
        "stale_acceptances": [],
        "counts": {"critical": 0, "drift": 0, "suggestion": 0, "accepted": 0},
        "threshold": "drift",
        "blocking": blocking,
        "strategies_run": [],
    }


class TestExitCodes:
    def test_clean_sweep_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub_run(monkeypatch, verdict())

        assert CliRunner().invoke(doctor, ["run"]).exit_code == 0

    def test_blocking_finding_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub_run(monkeypatch, verdict(blocking=2))

        assert CliRunner().invoke(doctor, ["run"]).exit_code == 1

    def test_failed_sweep_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "dev10x.commands.doctor.run_doctor",
            lambda **_kwargs: err("strategy 'broken' failed: boom", strategy_id="broken"),
        )

        assert CliRunner().invoke(doctor, ["run"]).exit_code == 2


class TestOutput:
    def test_verdict_is_json_on_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub_run(monkeypatch, verdict())

        result = CliRunner().invoke(doctor, ["run"])

        assert json.loads(result.output)["threshold"] == "drift"

    def test_error_is_json_on_stdout_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # One channel to parse, never an empty stdout on failure.
        monkeypatch.setattr(
            "dev10x.commands.doctor.run_doctor",
            lambda **_kwargs: err("boom", strategy_id="broken"),
        )

        result = CliRunner().invoke(doctor, ["run"])

        assert json.loads(result.output) == {"error": "boom", "strategy_id": "broken"}


class TestOptions:
    def test_threshold_reaches_the_runner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        def capture(**kwargs: Any) -> Any:
            seen.update(kwargs)
            return ok(verdict())

        monkeypatch.setattr("dev10x.commands.doctor.run_doctor", capture)

        CliRunner().invoke(doctor, ["run", "--threshold", "critical"])

        assert seen["threshold"] == "critical"

    def test_project_root_reaches_the_context_builder(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            "dev10x.commands.doctor.build_context",
            lambda project_root: seen.setdefault("root", project_root) and Context(),
        )
        stub_run(monkeypatch, verdict())

        CliRunner().invoke(doctor, ["run", "--project-root", str(tmp_path)])

        assert str(seen["root"]) == str(tmp_path)

    def test_an_unknown_threshold_is_refused(self) -> None:
        assert CliRunner().invoke(doctor, ["run", "--threshold", "spicy"]).exit_code == 2
