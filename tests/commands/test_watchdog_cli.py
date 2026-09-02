"""CLI surface for `dev10x watchdog` (GH-1109)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.cli import cli
from dev10x.domain.common.result import err, ok


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestRegistration:
    def test_watchdog_is_listed(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "watchdog" in result.output

    def test_subcommands_are_exposed(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["watchdog", "--help"])
        assert result.exit_code == 0
        for name in ("probe", "sessions", "wake"):
            assert name in result.output


class TestProbe:
    def test_json_output(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "dev10x.domain.watchdog.quota_state",
            lambda **_: ok({"block_available": True, "active_block": None}),
        )
        result = runner.invoke(cli, ["watchdog", "probe", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["block_available"] is True

    def test_error_exits_non_zero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "dev10x.domain.watchdog.quota_state", lambda **_: err("no transcripts")
        )
        result = runner.invoke(cli, ["watchdog", "probe"])
        assert result.exit_code == 1


class TestSessions:
    def test_lists_candidates(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "dev10x.domain.watchdog.find_paused_runs",
            lambda **_: ok({"candidates": [{"run_dir": "/runs/a"}], "count": 1}),
        )
        result = runner.invoke(
            cli, ["watchdog", "sessions", "--run-root", str(tmp_path), "--json"]
        )
        assert result.exit_code == 0
        assert json.loads(result.output)["count"] == 1

    def test_run_root_is_required(self, runner: CliRunner) -> None:
        # A watchdog with nowhere to look must fail loudly, not report
        # "nothing paused" and exit 0 forever.
        result = runner.invoke(cli, ["watchdog", "sessions"])
        assert result.exit_code != 0
        assert "run-root" in result.output


class TestWake:
    def test_wake_command_is_required(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["watchdog", "wake", "--run-root", str(tmp_path)])
        assert result.exit_code != 0
        assert "wake-command" in result.output

    def test_wake_command_is_shell_split(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen: dict[str, object] = {}

        def _fake_wake(**kwargs: object):
            seen.update(kwargs)
            return ok({"woken": []})

        monkeypatch.setattr("dev10x.domain.watchdog.wake", _fake_wake)
        result = runner.invoke(
            cli,
            [
                "watchdog",
                "wake",
                "--run-root",
                str(tmp_path),
                "--wake-command",
                "claude --resume",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert seen["wake_command"] == ["claude", "--resume"]
        assert seen["dry_run"] is True

    def test_json_error_goes_to_stdout(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # --json makes stdout a parsed surface, so a consumer must never
        # see empty stdout on failure.
        monkeypatch.setattr(
            "dev10x.domain.watchdog.wake", lambda **_: err("no run roots configured")
        )
        result = runner.invoke(
            cli,
            [
                "watchdog",
                "wake",
                "--run-root",
                str(tmp_path),
                "--wake-command",
                "nudge",
                "--json",
            ],
        )
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error"] == "no run roots configured"
