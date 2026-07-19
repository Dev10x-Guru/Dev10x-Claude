from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.skills.foreman import (
    WatchState,
    active_quota_block,
    base_branch_sha,
    block_identity,
    heartbeat_lines,
    newest_heartbeat_age_min,
)
from dev10x.skills.foreman import watch as watch_module

NOW = 1_000_000_000.0


@pytest.fixture
def state() -> WatchState:
    return WatchState(
        stall_min=25,
        cost_step=50,
        known_sha="aaa111",
        known_block_id="2026-07-19T07:00:00.000Z",
        known_cost_bucket=1,
        started_at=NOW,
    )


@pytest.fixture
def quiet_block() -> dict:
    return {"id": "2026-07-19T07:00:00.000Z", "costUSD": 60.0}


def _touch(path: Path, *, age_min: float, content: str = "- t phase: line") -> None:
    path.write_text(content, encoding="utf-8")
    stamp = NOW - age_min * 60
    os.utime(path, (stamp, stamp))


class TestWatchStateObserve:
    def test_quiet_round_emits_nothing(self, state: WatchState, quiet_block: dict) -> None:
        events = state.observe(now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=1)
        assert events == []

    def test_stall_fires_after_threshold(self, state: WatchState, quiet_block: dict) -> None:
        events = state.observe(now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=26)
        assert events == ["STALL: newest heartbeat silent for 26 min"]

    def test_stall_alert_is_rate_limited(self, state: WatchState, quiet_block: dict) -> None:
        state.observe(now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=26)
        repeat = state.observe(
            now=NOW + 120, sha="aaa111", block=quiet_block, heartbeat_age_min=27
        )
        assert repeat == []

    def test_stall_realerts_after_window(self, state: WatchState, quiet_block: dict) -> None:
        state.observe(now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=26)
        later = state.observe(
            now=NOW + 60 + 25 * 60, sha="aaa111", block=quiet_block, heartbeat_age_min=51
        )
        assert later == ["STALL: newest heartbeat silent for 51 min"]

    def test_missing_heartbeats_grace_until_run_age(
        self, state: WatchState, quiet_block: dict
    ) -> None:
        early = state.observe(
            now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=None
        )
        assert early == []
        late = state.observe(
            now=NOW + 26 * 60, sha="aaa111", block=quiet_block, heartbeat_age_min=None
        )
        assert late == ["STALL: newest heartbeat silent for 26 min"]

    def test_base_movement_emits_and_rebaselines(
        self, state: WatchState, quiet_block: dict
    ) -> None:
        events = state.observe(now=NOW + 60, sha="bbb222", block=quiet_block, heartbeat_age_min=1)
        assert events == ["BASE MOVED: aaa111 -> bbb222"]
        again = state.observe(now=NOW + 120, sha="bbb222", block=quiet_block, heartbeat_age_min=1)
        assert again == []

    def test_empty_sha_is_transient_not_movement(
        self, state: WatchState, quiet_block: dict
    ) -> None:
        events = state.observe(now=NOW + 60, sha="", block=quiet_block, heartbeat_age_min=1)
        assert events == []
        assert state.known_sha == "aaa111"

    def test_cost_milestone_fires_per_step(self, state: WatchState) -> None:
        block = {"id": "2026-07-19T07:00:00.000Z", "costUSD": 104.0}
        events = state.observe(now=NOW + 60, sha="aaa111", block=block, heartbeat_age_min=1)
        assert events == ["QUOTA MILESTONE: block cost crossed $100"]

    def test_block_rollover_emits_reset_and_zeroes_bucket(self, state: WatchState) -> None:
        block = {"id": "2026-07-19T12:00:00.000Z", "costUSD": 3.0}
        events = state.observe(now=NOW + 60, sha="aaa111", block=block, heartbeat_age_min=1)
        assert events == [
            "QUOTA RESET: new 5h block 2026-07-19T12:00:00.000Z — resume interrupted crew"
        ]
        assert state.known_cost_bucket == 0

    def test_first_block_sighting_is_silent(self, quiet_block: dict) -> None:
        fresh = WatchState(
            stall_min=25,
            cost_step=50,
            known_sha="aaa111",
            known_block_id="",
            known_cost_bucket=0,
            started_at=NOW,
        )
        events = fresh.observe(now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=1)
        assert events == ["QUOTA MILESTONE: block cost crossed $50"]
        assert fresh.known_block_id == "2026-07-19T07:00:00.000Z"


class TestHeartbeatReaders:
    def test_age_uses_freshest_file_mtime(self, tmp_path: Path) -> None:
        _touch(tmp_path / "status-m1.md", age_min=40)
        _touch(tmp_path / "status-m2.md", age_min=3)
        assert newest_heartbeat_age_min(scratchpad=tmp_path, now=NOW) == 3

    def test_age_is_none_without_files(self, tmp_path: Path) -> None:
        assert newest_heartbeat_age_min(scratchpad=tmp_path, now=NOW) is None

    def test_lines_report_age_and_last_line(self, tmp_path: Path) -> None:
        _touch(tmp_path / "status-m1.md", age_min=2, content="- one\n- two")
        lines = heartbeat_lines(scratchpad=tmp_path, now=time.time())
        assert len(lines) == 1
        assert "status-m1.md" in lines[0]
        assert lines[0].endswith("last=- two")

    def test_lines_mark_empty_files(self, tmp_path: Path) -> None:
        _touch(tmp_path / "status-m1.md", age_min=2, content="")
        lines = heartbeat_lines(scratchpad=tmp_path, now=time.time())
        assert lines[0].endswith("last=(empty)")


class TestBlockIdentity:
    def test_prefers_id(self) -> None:
        assert block_identity({"id": "A", "startTime": "B"}) == "A"

    def test_falls_back_to_start_time(self) -> None:
        assert block_identity({"startTime": "B"}) == "B"

    def test_empty_block(self) -> None:
        assert block_identity({}) == ""


class TestQuotaBlockGateway:
    def test_returns_active_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: ok({"blocks": [{"id": "A"}]}),
        )
        assert active_quota_block() == {"id": "A"}

    def test_empty_on_error_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: err("no usage data"),
        )
        assert active_quota_block() == {}

    def test_empty_when_no_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: ok({"blocks": []}),
        )
        assert active_quota_block() == {}


class TestBaseBranchShaGateway:
    @pytest.fixture
    def captured(self) -> dict:
        return {}

    @pytest.fixture
    def fake_run(self, monkeypatch: pytest.MonkeyPatch, captured: dict):
        def _fake_run(args: list[str], **kwargs: object):
            captured["args"] = args
            captured["kwargs"] = kwargs

            class _Completed:
                stdout = "abc123\trefs/heads/develop\n"

            return _Completed()

        monkeypatch.setattr(watch_module.subprocess_utils, "run", _fake_run)

    def test_parses_sha_and_targets_branch(self, fake_run: None, captured: dict) -> None:
        sha = base_branch_sha(base_branch="develop", repo=Path("/repo"))
        assert sha == "abc123"
        assert captured["args"] == ["git", "ls-remote", "origin", "refs/heads/develop"]
        assert captured["kwargs"]["cwd"] == "/repo"

    def test_defaults_cwd_and_handles_empty_output(
        self, monkeypatch: pytest.MonkeyPatch, captured: dict
    ) -> None:
        def _fake_run(args: list[str], **kwargs: object):
            captured["kwargs"] = kwargs

            class _Completed:
                stdout = ""

            return _Completed()

        monkeypatch.setattr(watch_module.subprocess_utils, "run", _fake_run)
        assert base_branch_sha(base_branch="develop") == ""
        assert captured["kwargs"]["cwd"] is None
