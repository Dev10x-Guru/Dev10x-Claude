"""Tests for the probes that feed the supervisor snapshot (GH-1692)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.skills.bus.maildir import SessionStatus, write_status
from dev10x.comm.supervisor.probes import (
    PROBE_TIMEOUT_SECONDS,
    ProbeError,
    Snapshot,
    read_pane,
    send_keys,
    take_snapshot,
)
from tests.comm.supervisor.conftest import IDLE_ID, NOW, WAITING_ID

Runner = Callable[..., subprocess.CompletedProcess[str]]


class FakeRunner:
    def __init__(
        self,
        *,
        outputs: dict[str, str] | None = None,
        failures: dict[str, BaseException] | None = None,
        returncode: int = 0,
    ) -> None:
        self.outputs = outputs or {}
        self.failures = failures or {}
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, kwargs))
        if args[0] in self.failures:
            raise self.failures[args[0]]
        return subprocess.CompletedProcess(
            args=args,
            returncode=self.returncode,
            stdout=self.outputs.get(args[0], ""),
            stderr="boom" if self.returncode else "",
        )


@pytest.fixture
def bus_root(tmp_path: Path) -> Path:
    root = tmp_path / "bus"
    write_status(
        root=root,
        status=SessionStatus(
            mailbox="mc-updates",
            state="working",
            summary="Collecting statuses.",
            updated=NOW,
            callsign="status round",
        ),
    )
    return root


@pytest.fixture
def healthy_runner(claude_agents_json: str, herdr_agents_json: str) -> FakeRunner:
    return FakeRunner(outputs={"claude": claude_agents_json, "herdr": herdr_agents_json})


class TestTakeSnapshot:
    @pytest.fixture
    def snapshot(self, bus_root: Path, healthy_runner: FakeRunner) -> Snapshot:
        return take_snapshot(bus_root=bus_root, runner=healthy_runner)

    def test_merges_all_sources(self, snapshot: Snapshot) -> None:
        views = {view.session_id: view for view in snapshot.sessions}

        assert (views[WAITING_ID].pane_id, views[IDLE_ID].callsign, snapshot.errors) == (
            "w3:p1",
            "status round",
            {},
        )

    def test_bounds_every_probe(self, bus_root: Path, healthy_runner: FakeRunner) -> None:
        take_snapshot(bus_root=bus_root, runner=healthy_runner)

        assert {kwargs["timeout"] for _, kwargs in healthy_runner.calls} == {PROBE_TIMEOUT_SECONDS}

    def test_probe_missing_binary(self, bus_root: Path, claude_agents_json: str) -> None:
        runner = FakeRunner(
            outputs={"claude": claude_agents_json},
            failures={"herdr": FileNotFoundError("herdr")},
        )

        snapshot = take_snapshot(bus_root=bus_root, runner=runner)

        assert (len(snapshot.sessions), "herdr" in snapshot.errors["herdr"]) == (3, True)

    def test_probe_timeout(self, bus_root: Path, herdr_agents_json: str) -> None:
        runner = FakeRunner(
            outputs={"herdr": herdr_agents_json},
            failures={"claude": subprocess.TimeoutExpired(cmd="claude", timeout=10)},
        )

        snapshot = take_snapshot(bus_root=bus_root, runner=runner)

        assert (snapshot.sessions, "timed out" in snapshot.errors["claude"]) == ([], True)

    def test_probe_bad_output(self, bus_root: Path, herdr_agents_json: str) -> None:
        runner = FakeRunner(outputs={"claude": "oops", "herdr": herdr_agents_json})

        snapshot = take_snapshot(bus_root=bus_root, runner=runner)

        assert "invalid JSON" in snapshot.errors["claude"]

    def test_probe_non_zero_exit(self, bus_root: Path) -> None:
        snapshot = take_snapshot(bus_root=bus_root, runner=FakeRunner(returncode=2))

        assert "boom" in snapshot.errors["claude"]

    def test_unreadable_board_line_is_skipped(
        self,
        bus_root: Path,
        healthy_runner: FakeRunner,
    ) -> None:
        (bus_root / "status" / "broken").write_text("not a status", encoding="utf-8")

        snapshot = take_snapshot(bus_root=bus_root, runner=healthy_runner)

        assert snapshot.errors == {}

    def test_unreadable_board_is_reported(
        self,
        bus_root: Path,
        healthy_runner: FakeRunner,
    ) -> None:
        board_dir = bus_root / "status"
        board_dir.chmod(0)
        try:
            snapshot = take_snapshot(bus_root=bus_root, runner=healthy_runner)
        finally:
            board_dir.chmod(0o700)

        assert (len(snapshot.sessions), "bus" in snapshot.errors) == (3, True)


class TestPaneCommands:
    def test_read_pane_passes_lines_and_source(self) -> None:
        runner = FakeRunner(outputs={"herdr": "line\n"})

        text = read_pane(pane_id="w1:p1", runner=runner)

        assert (runner.calls[0][0], text) == (
            [
                "herdr",
                "agent",
                "read",
                "w1:p1",
                "--source",
                "recent",
                "--lines",
                "20",
                "--format",
                "text",
            ],
            "line\n",
        )

    def test_read_pane_failure_returns_empty(self) -> None:
        runner = FakeRunner(failures={"herdr": FileNotFoundError("herdr")})

        assert read_pane(pane_id="w1:p1", runner=runner) == ""

    def test_send_keys_args(self) -> None:
        runner = FakeRunner()

        send_keys(pane_id="w1:p1", keys=["2"], runner=runner)

        assert runner.calls[0][0] == ["herdr", "agent", "send-keys", "w1:p1", "2"]

    def test_send_keys_raises_on_failure(self) -> None:
        with pytest.raises(ProbeError, match="boom"):
            send_keys(pane_id="w1:p1", keys=["1"], runner=FakeRunner(returncode=1))

    def test_send_keys_raises_when_herdr_missing(self) -> None:
        runner = FakeRunner(failures={"herdr": FileNotFoundError("herdr")})

        with pytest.raises(ProbeError, match="herdr"):
            send_keys(pane_id="w1:p1", keys=["1"], runner=runner)
