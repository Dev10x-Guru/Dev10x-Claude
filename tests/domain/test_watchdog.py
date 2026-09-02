"""Tests for the quota-pause wake watchdog (GH-1109)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dev10x.domain import watchdog
from dev10x.domain.common.result import ErrorResult, SuccessResult, ok

NOW = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)


@pytest.fixture()
def state_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Drive the REAL path resolution through the documented env var
    # rather than patching the private seam, so `_state_path` itself is
    # exercised.
    config_home = tmp_path / "config"
    monkeypatch.setenv("DEV10X_CONFIG_HOME", str(config_home))
    from dev10x.domain.dev10x_paths import Dev10xConfigDir

    Dev10xConfigDir.reset_cache()
    return config_home / "watchdog-state.json"


@pytest.fixture()
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


def _make_run(root: Path, name: str, *, silent_minutes: int) -> Path:
    run_dir = root / name
    run_dir.mkdir()
    beat = run_dir / "status-foreman.md"
    beat.write_text("working\n")
    stamp = (NOW - timedelta(minutes=silent_minutes)).timestamp()
    os.utime(beat, (stamp, stamp))
    return run_dir


class TestFindPausedRuns:
    def test_reports_a_silent_run(self, run_root: Path) -> None:
        _make_run(run_root, "night-a", silent_minutes=45)
        result = watchdog.find_paused_runs(run_roots=[run_root], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 1
        assert result.value["candidates"][0]["silent_for_minutes"] == 45

    def test_ignores_a_fresh_run(self, run_root: Path) -> None:
        _make_run(run_root, "night-a", silent_minutes=2)
        result = watchdog.find_paused_runs(run_roots=[run_root], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 0

    def test_ignores_a_run_with_no_heartbeats(self, run_root: Path) -> None:
        # Not started is not paused — there is nothing to wake.
        (run_root / "night-empty").mkdir()
        result = watchdog.find_paused_runs(run_roots=[run_root], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 0

    def test_missing_root_is_not_an_error(self, tmp_path: Path) -> None:
        result = watchdog.find_paused_runs(run_roots=[tmp_path / "absent"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 0

    def test_no_run_roots_is_an_error(self) -> None:
        # A watchdog with nowhere to look must not report "nothing paused".
        assert isinstance(watchdog.find_paused_runs(run_roots=[], now=NOW), ErrorResult)

    def test_a_dangling_heartbeat_symlink_is_skipped(self, run_root: Path) -> None:
        # A heartbeat deleted between glob and stat is normal against a
        # live run and must not fail the whole sweep.
        run_dir = _make_run(run_root, "night-a", silent_minutes=60)
        (run_dir / "status-gone.md").symlink_to(run_dir / "nonexistent.md")
        result = watchdog.find_paused_runs(run_roots=[run_root], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 1

    def test_a_run_with_only_a_dangling_heartbeat_is_ignored(self, run_root: Path) -> None:
        run_dir = run_root / "night-broken"
        run_dir.mkdir()
        (run_dir / "status-gone.md").symlink_to(run_dir / "nonexistent.md")
        result = watchdog.find_paused_runs(run_roots=[run_root], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 0

    def test_two_roots_are_both_swept(self, tmp_path: Path) -> None:
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()
        _make_run(first, "night-a", silent_minutes=60)
        _make_run(second, "night-b", silent_minutes=60)
        result = watchdog.find_paused_runs(run_roots=[first, second], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 2

    def test_newest_heartbeat_decides_silence(self, run_root: Path) -> None:
        # A run is only paused when EVERY role has gone quiet.
        run_dir = _make_run(run_root, "night-a", silent_minutes=90)
        fresh = run_dir / "status-worker.md"
        fresh.write_text("still going\n")
        stamp = (NOW - timedelta(minutes=1)).timestamp()
        os.utime(fresh, (stamp, stamp))
        result = watchdog.find_paused_runs(run_roots=[run_root], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["count"] == 0


class TestQuotaState:
    def test_block_available_when_none_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dev10x.domain.usage.blocks_report", lambda **_: ok({"blocks": []}))
        result = watchdog.quota_state(now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["block_available"] is True

    def test_block_not_available_while_one_is_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "dev10x.domain.usage.blocks_report",
            lambda **_: ok({"blocks": [{"id": "b1", "startTime": "2026-09-01T05:00:00Z"}]}),
        )
        result = watchdog.quota_state(now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["block_available"] is False

    def test_propagates_a_reader_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dev10x.domain.common.result import err

        monkeypatch.setattr("dev10x.domain.usage.blocks_report", lambda **_: err("no transcripts"))
        assert isinstance(watchdog.quota_state(now=NOW), ErrorResult)

    def test_injected_clock_reaches_the_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # blocks_report decides activeness from `now`; omitting it made the
        # report internally inconsistent under an injected clock.
        seen: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> Any:
            seen.update(kwargs)
            return ok({"blocks": []})

        monkeypatch.setattr("dev10x.domain.usage.blocks_report", _capture)
        watchdog.quota_state(now=NOW)
        assert seen["now"] == NOW


@pytest.fixture()
def no_active_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dev10x.domain.usage.blocks_report", lambda **_: ok({"blocks": []}))


@pytest.fixture()
def fired(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def _fake_run(args: list[str], **_: Any) -> Any:
        calls.append(args)

        class _Done:
            returncode = 0
            stderr = ""

        return _Done()

    monkeypatch.setattr("dev10x.domain.watchdog.subprocess.run", _fake_run)
    return calls


class TestWake:
    def test_requires_a_wake_command(self, run_root: Path) -> None:
        result = watchdog.wake(run_roots=[run_root], wake_command=[], now=NOW)
        assert isinstance(result, ErrorResult)

    def test_skips_a_block_the_run_itself_is_using(
        self, run_root: Path, monkeypatch: pytest.MonkeyPatch, state_path: Path
    ) -> None:
        # The block opened BEFORE the run went silent, so it is the run's
        # own block — a pause inside it is not a reset to wake for.
        monkeypatch.setattr(
            "dev10x.domain.usage.blocks_report",
            lambda **_: ok({"blocks": [{"id": "b1", "startTime": "2026-09-01T04:00:00Z"}]}),
        )
        _make_run(run_root, "night-a", silent_minutes=60)  # last beat 05:00Z
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["woken"] == []
        assert result.value["skipped"][0]["reason"] == "block still active"

    def test_wakes_when_a_new_block_opened_after_the_run_went_silent(
        self,
        run_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        # Someone else's session opened a block after the pause. Capacity
        # is being used by them and wasted by the paused run — the exact
        # window GH-1109 is about, which "no active block" alone misses.
        monkeypatch.setattr(
            "dev10x.domain.usage.blocks_report",
            lambda **_: ok({"blocks": [{"id": "b2", "startTime": "2026-09-01T05:30:00Z"}]}),
        )
        _make_run(run_root, "night-a", silent_minutes=60)  # last beat 05:00Z
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert len(fired) == 1
        assert "opened after this run went silent" in result.value["woken"][0]["reason"]

    def test_propagates_a_quota_error(
        self, run_root: Path, monkeypatch: pytest.MonkeyPatch, state_path: Path
    ) -> None:
        from dev10x.domain.common.result import err

        monkeypatch.setattr("dev10x.domain.usage.blocks_report", lambda **_: err("no data"))
        _make_run(run_root, "night-a", silent_minutes=60)
        assert isinstance(
            watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW),
            ErrorResult,
        )

    def test_a_timed_out_wake_returns_a_result_not_a_traceback(
        self,
        run_root: Path,
        no_active_block: None,
        state_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # TimeoutExpired is a SubprocessError, not an OSError — the case
        # the timeout exists to create must not escape a cron job.
        def _timeout(*_a: Any, **_k: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="nudge", timeout=60)

        monkeypatch.setattr("dev10x.domain.watchdog.subprocess.run", _timeout)
        _make_run(run_root, "night-a", silent_minutes=60)
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["woken"][0]["ok"] is False

    def test_a_missing_wake_binary_returns_a_result(
        self,
        run_root: Path,
        no_active_block: None,
        state_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _missing(*_a: Any, **_k: Any) -> Any:
            raise FileNotFoundError("no such binary")

        monkeypatch.setattr("dev10x.domain.watchdog.subprocess.run", _missing)
        _make_run(run_root, "night-a", silent_minutes=60)
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["woken"][0]["ok"] is False

    def test_a_latch_lock_failure_returns_a_result(
        self,
        run_root: Path,
        no_active_block: None,
        state_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.domain import file_locks

        def _no_lock(*_a: Any, **_k: Any) -> Any:
            raise file_locks.LockTimeoutError("contended")

        monkeypatch.setattr("dev10x.domain.file_locks.file_lock", _no_lock)
        _make_run(run_root, "night-a", silent_minutes=60)
        assert isinstance(
            watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW),
            ErrorResult,
        )

    def test_no_run_roots_propagates_as_an_error(
        self, no_active_block: None, state_path: Path
    ) -> None:
        assert isinstance(
            watchdog.wake(run_roots=[], wake_command=["nudge"], now=NOW), ErrorResult
        )

    @pytest.mark.parametrize(
        "active",
        [
            "not-a-dict",
            {"id": "b1"},  # no startTime at all
            {"id": "b1", "startTime": "not-a-timestamp"},
            {"id": "b1", "startTime": ""},
        ],
        ids=["non-dict", "no-start", "unparseable-start", "empty-start"],
    )
    def test_an_unusable_active_block_skips_rather_than_guesses(
        self,
        run_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        fired: list[list[str]],
        state_path: Path,
        active: Any,
    ) -> None:
        # Without a usable start time there is no way to tell whose block
        # this is, so leave the run alone rather than nudge on a guess.
        monkeypatch.setattr(
            "dev10x.domain.usage.blocks_report", lambda **_: ok({"blocks": [active]})
        )
        _make_run(run_root, "night-a", silent_minutes=60)
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["woken"] == []
        assert fired == []

    def test_prunes_entries_for_vanished_run_dirs(
        self,
        run_root: Path,
        no_active_block: None,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"woken": {"/gone/night-old": "gap:x"}}))
        _make_run(run_root, "night-a", silent_minutes=60)
        watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert "/gone/night-old" not in json.loads(state_path.read_text())["woken"]

    def test_wakes_a_paused_run(
        self,
        run_root: Path,
        no_active_block: None,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        run_dir = _make_run(run_root, "night-a", silent_minutes=60)
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge", "--now"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["woken"] == [
            {
                "run_dir": str(run_dir),
                "reason": "no active block — capacity is free",
                "ok": True,
            }
        ]
        assert fired == [["nudge", "--now", str(run_dir)]]

    def test_is_idempotent_within_one_boundary(
        self,
        run_root: Path,
        no_active_block: None,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        _make_run(run_root, "night-a", silent_minutes=60)
        watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        second = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert isinstance(second, SuccessResult)
        assert second.value["woken"] == []
        assert len(second.value["already_woken"]) == 1
        assert len(fired) == 1, "a five-minute timer must not re-nudge the same boundary"

    def test_wakes_again_at_the_next_boundary(
        self,
        run_root: Path,
        no_active_block: None,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        _make_run(run_root, "night-a", silent_minutes=60)
        watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        watchdog.wake(
            run_roots=[run_root],
            wake_command=["nudge"],
            now=NOW + timedelta(hours=6),
        )
        assert len(fired) == 2

    def test_dry_run_fires_nothing_and_latches_nothing(
        self,
        run_root: Path,
        no_active_block: None,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        _make_run(run_root, "night-a", silent_minutes=60)
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW, dry_run=True)
        assert isinstance(result, SuccessResult)
        assert result.value["woken"][0]["dry_run"] is True
        assert fired == []
        assert not state_path.exists()

    def test_a_failing_wake_is_not_latched(
        self,
        run_root: Path,
        no_active_block: None,
        state_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _Failed:
            returncode = 3
            stderr = "boom"

        monkeypatch.setattr("dev10x.domain.watchdog.subprocess.run", lambda *a, **k: _Failed())
        run_dir = _make_run(run_root, "night-a", silent_minutes=60)
        result = watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert isinstance(result, SuccessResult)
        assert result.value["woken"][0]["ok"] is False
        # Not latching a failure is what lets the next timer tick retry.
        assert str(run_dir) not in json.loads(state_path.read_text())["woken"]

    def test_a_corrupt_latch_does_not_suppress_a_wake(
        self,
        run_root: Path,
        no_active_block: None,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{ not json")
        _make_run(run_root, "night-a", silent_minutes=60)
        watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        assert len(fired) == 1

    def test_latch_records_the_boundary_per_run(
        self,
        run_root: Path,
        no_active_block: None,
        fired: list[list[str]],
        state_path: Path,
    ) -> None:
        run_dir = _make_run(run_root, "night-a", silent_minutes=60)
        watchdog.wake(run_roots=[run_root], wake_command=["nudge"], now=NOW)
        data = json.loads(state_path.read_text())
        assert data["woken"][str(run_dir)].startswith("gap:")
