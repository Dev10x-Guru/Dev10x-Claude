from __future__ import annotations

import logging
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
    historical_token_ceiling,
    is_own_merge,
    minutes_to_quota_exhaustion,
    newest_heartbeat_age_min,
    own_merge_shas,
    queue_parked,
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


class TestOwnMergeAndParkedReaders:
    def test_parked_flag_absent(self, tmp_path: Path) -> None:
        assert watch_module.queue_parked(scratchpad=tmp_path) is False

    def test_parked_flag_present(self, tmp_path: Path) -> None:
        (tmp_path / "parked").write_text("burn gate hold\n", encoding="utf-8")
        assert watch_module.queue_parked(scratchpad=tmp_path) is True

    def test_merged_shas_missing_file(self, tmp_path: Path) -> None:
        assert watch_module.own_merge_shas(scratchpad=tmp_path) == set()

    def test_merged_shas_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        (tmp_path / "merged-shas").write_text(
            "# chunk 1\nabc1234def\n\n  def5678abc  # chunk 2\n",
            encoding="utf-8",
        )
        assert watch_module.own_merge_shas(scratchpad=tmp_path) == {"abc1234def", "def5678abc"}

    def test_own_merge_matches_abbreviated_either_way(self) -> None:
        assert watch_module.is_own_merge(sha="abc1234def567", merged_shas={"abc1234"}) is True
        assert watch_module.is_own_merge(sha="abc1234", merged_shas={"abc1234def567"}) is True

    def test_own_merge_rejects_unknown_sha(self) -> None:
        assert watch_module.is_own_merge(sha="fff9999", merged_shas={"abc1234"}) is False

    def test_own_merge_ignores_ambiguous_stubs(self) -> None:
        assert watch_module.is_own_merge(sha="abc", merged_shas={"abc1234def"}) is False
        assert watch_module.is_own_merge(sha="abc1234def", merged_shas={"abc"}) is False

    def test_package_reexports_new_helpers(self) -> None:
        assert (queue_parked, own_merge_shas, is_own_merge) == (
            watch_module.queue_parked,
            watch_module.own_merge_shas,
            watch_module.is_own_merge,
        )


class TestParkedAndOwnMergeMuting:
    def test_own_merge_echo_is_muted_but_rebaselined(
        self, state: WatchState, quiet_block: dict
    ) -> None:
        events = state.observe(
            now=NOW + 60,
            sha="bbb2222aaa",
            block=quiet_block,
            heartbeat_age_min=1,
            merged_shas={"bbb2222"},
        )
        assert events == []
        assert state.known_sha == "bbb2222aaa"

    def test_external_landing_still_reported(self, state: WatchState, quiet_block: dict) -> None:
        events = state.observe(
            now=NOW + 60,
            sha="ccc3333aaa",
            block=quiet_block,
            heartbeat_age_min=1,
            merged_shas={"bbb2222"},
        )
        assert events == ["BASE MOVED: aaa111 -> ccc3333aaa"]

    def test_parked_mutes_stall_alarm(self, state: WatchState, quiet_block: dict) -> None:
        events = state.observe(
            now=NOW + 60,
            sha="aaa111",
            block=quiet_block,
            heartbeat_age_min=90,
            parked=True,
        )
        assert events == []

    def test_parked_mutes_quota_milestones(self, state: WatchState) -> None:
        block = {"id": "2026-07-19T07:00:00.000Z", "costUSD": 104.0}
        events = state.observe(
            now=NOW + 60, sha="aaa111", block=block, heartbeat_age_min=1, parked=True
        )
        assert events == []
        assert state.muted_milestones == 1

    def test_release_rolls_up_muted_milestones(self, state: WatchState) -> None:
        state.observe(
            now=NOW + 60,
            sha="aaa111",
            block={"id": "2026-07-19T07:00:00.000Z", "costUSD": 104.0},
            heartbeat_age_min=1,
            parked=True,
        )
        state.observe(
            now=NOW + 120,
            sha="aaa111",
            block={"id": "2026-07-19T07:00:00.000Z", "costUSD": 155.0},
            heartbeat_age_min=1,
            parked=True,
        )
        released = state.observe(
            now=NOW + 180,
            sha="aaa111",
            block={"id": "2026-07-19T07:00:00.000Z", "costUSD": 155.0},
            heartbeat_age_min=1,
        )
        assert released == [
            "QUOTA MILESTONE (parked rollup): 2 muted while parked, block cost now $155"
        ]
        assert state.muted_milestones == 0

    def test_release_without_muted_milestones_is_silent(
        self, state: WatchState, quiet_block: dict
    ) -> None:
        state.observe(
            now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=1, parked=True
        )
        released = state.observe(
            now=NOW + 120, sha="aaa111", block=quiet_block, heartbeat_age_min=1
        )
        assert released == []

    def test_release_grants_one_stall_grace_window(
        self, state: WatchState, quiet_block: dict
    ) -> None:
        state.observe(
            now=NOW + 60, sha="aaa111", block=quiet_block, heartbeat_age_min=90, parked=True
        )
        released = state.observe(
            now=NOW + 120, sha="aaa111", block=quiet_block, heartbeat_age_min=91
        )
        assert released == []
        later = state.observe(
            now=NOW + 120 + 25 * 60, sha="aaa111", block=quiet_block, heartbeat_age_min=115
        )
        assert later == ["STALL: newest heartbeat silent for 115 min"]

    def test_quota_reset_still_fires_while_parked(self, state: WatchState) -> None:
        block = {"id": "2026-07-19T12:00:00.000Z", "costUSD": 3.0}
        events = state.observe(
            now=NOW + 60, sha="aaa111", block=block, heartbeat_age_min=1, parked=True
        )
        assert events == [
            "QUOTA RESET: new 5h block 2026-07-19T12:00:00.000Z — resume interrupted crew"
        ]


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
                returncode = 0

            return _Completed()

        monkeypatch.setattr(watch_module.subprocess_utils, "run", _fake_run)

    def test_parses_sha_and_targets_branch(self, fake_run: None, captured: dict) -> None:
        sha = base_branch_sha(base_branch="develop", repo=Path("/repo"))
        assert sha == "abc123"
        assert captured["args"] == ["git", "ls-remote", "origin", "refs/heads/develop"]
        assert captured["kwargs"]["cwd"] == "/repo"

    def test_asks_the_remote_never_the_local_ref(self, fake_run: None, captured: dict) -> None:
        # GH-964: merge-coordination tooling must report the remote base.
        # `rev-parse`/`merge-base` against a local ref answers "what does
        # this worktree think the base is" and goes stale until a fetch.
        base_branch_sha(base_branch="develop", repo=Path("/repo"))
        assert captured["args"][1] == "ls-remote"
        assert "rev-parse" not in captured["args"]
        assert "merge-base" not in captured["args"]

    def test_defaults_cwd_and_handles_empty_output(
        self, monkeypatch: pytest.MonkeyPatch, captured: dict
    ) -> None:
        def _fake_run(args: list[str], **kwargs: object):
            captured["kwargs"] = kwargs

            class _Completed:
                stdout = ""
                returncode = 128

            return _Completed()

        monkeypatch.setattr(watch_module.subprocess_utils, "run", _fake_run)
        assert base_branch_sha(base_branch="develop") == ""
        assert captured["kwargs"]["cwd"] is None

    def test_logs_a_warning_when_the_remote_tip_is_unreachable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _fake_run(args: list[str], **kwargs: object):
            class _Completed:
                stdout = ""
                returncode = 128

            return _Completed()

        monkeypatch.setattr(watch_module.subprocess_utils, "run", _fake_run)
        with caplog.at_level(logging.WARNING, logger=watch_module.__name__):
            assert base_branch_sha(base_branch="develop") == ""
        assert "origin/develop" in caplog.text


class TestHistoricalTokenCeiling:
    def test_takes_the_highest_completed_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: ok(
                {
                    "blocks": [
                        {"id": "A", "isActive": False, "totalTokens": 400_000},
                        {"id": "B", "isActive": False, "totalTokens": 950_000},
                        {"id": "C", "isActive": True, "totalTokens": 5_000_000},
                    ]
                }
            ),
        )
        assert historical_token_ceiling() == 950_000

    def test_ignores_gap_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: ok(
                {
                    "blocks": [
                        {"id": "A", "isActive": False, "totalTokens": 400_000},
                        {"id": "gap", "isActive": False, "isGap": True, "totalTokens": 9_000_000},
                    ]
                }
            ),
        )
        assert historical_token_ceiling() == 400_000

    def test_zero_without_completed_history(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: ok({"blocks": [{"id": "C", "isActive": True}]}),
        )
        assert historical_token_ceiling() == 0

    def test_zero_on_error_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: err("no usage data"),
        )
        assert historical_token_ceiling() == 0


class TestMinutesToQuotaExhaustion:
    def test_divides_remaining_budget_by_burn_rate(self) -> None:
        block = {"totalTokens": 700_000, "burnRate": {"tokensPerMinute": 10_000}}
        assert minutes_to_quota_exhaustion(block=block, ceiling_tokens=1_000_000) == 30

    def test_zero_when_ceiling_already_spent(self) -> None:
        block = {"totalTokens": 1_200_000, "burnRate": {"tokensPerMinute": 10_000}}
        assert minutes_to_quota_exhaustion(block=block, ceiling_tokens=1_000_000) == 0

    def test_none_without_a_ceiling_estimate(self) -> None:
        block = {"totalTokens": 10, "burnRate": {"tokensPerMinute": 10_000}}
        assert minutes_to_quota_exhaustion(block=block, ceiling_tokens=0) is None

    def test_none_without_a_measured_burn_rate(self) -> None:
        assert minutes_to_quota_exhaustion(block={"totalTokens": 10}, ceiling_tokens=1_000) is None
        assert (
            minutes_to_quota_exhaustion(
                block={"totalTokens": 10, "burnRate": {"tokensPerMinute": 0}},
                ceiling_tokens=1_000,
            )
            is None
        )


class TestQuotaLowProjection:
    @pytest.fixture
    def burning(self) -> dict:
        # 300k of a 1M ceiling left at 20k/min → ~15 min of budget,
        # well inside both the 45-min chunk and the 120-min block.
        return {
            "id": "2026-07-19T07:00:00.000Z",
            "costUSD": 60.0,
            "totalTokens": 700_000,
            "remainingMinutes": 120,
            "burnRate": {"tokensPerMinute": 20_000},
        }

    @pytest.fixture
    def state(self) -> WatchState:
        return WatchState(
            stall_min=25,
            cost_step=50,
            known_sha="aaa111",
            known_block_id="2026-07-19T07:00:00.000Z",
            known_cost_bucket=1,
            started_at=NOW,
            chunk_min=45,
            quota_ceiling_tokens=1_000_000,
        )

    def test_fires_when_budget_runs_out_inside_the_chunk(
        self, state: WatchState, burning: dict
    ) -> None:
        events = state.observe(now=NOW + 60, sha="aaa111", block=burning, heartbeat_age_min=1)
        assert events == [
            "QUOTA LOW: ~15 min of block budget left at current burn "
            "(120 min to reset, chunk needs ~45) — "
            "checkpoint the in-flight chunk and park the queue"
        ]

    def test_fires_once_per_block(self, state: WatchState, burning: dict) -> None:
        state.observe(now=NOW + 60, sha="aaa111", block=burning, heartbeat_age_min=1)
        repeat = state.observe(now=NOW + 120, sha="aaa111", block=burning, heartbeat_age_min=1)
        assert repeat == []

    def test_rearms_after_a_block_rollover(self, state: WatchState, burning: dict) -> None:
        state.observe(now=NOW + 60, sha="aaa111", block=burning, heartbeat_age_min=1)
        next_block = dict(burning, id="2026-07-19T12:00:00.000Z")
        events = state.observe(now=NOW + 120, sha="aaa111", block=next_block, heartbeat_age_min=1)
        assert events[0].startswith("QUOTA RESET:")
        assert events[-1].startswith("QUOTA LOW:")

    def test_silent_when_budget_outlasts_the_chunk(self, state: WatchState, burning: dict) -> None:
        roomy = dict(burning, totalTokens=0)
        events = state.observe(now=NOW + 60, sha="aaa111", block=roomy, heartbeat_age_min=1)
        assert events == []

    def test_silent_when_exhaustion_lands_after_the_reset(
        self, state: WatchState, burning: dict
    ) -> None:
        # The reset refills the budget before the burn can spend it, so
        # there is nothing to park for.
        rolling_over = dict(burning, remainingMinutes=10)
        events = state.observe(now=NOW + 60, sha="aaa111", block=rolling_over, heartbeat_age_min=1)
        assert events == []

    def test_silent_without_a_ceiling_estimate(self, burning: dict) -> None:
        blind = WatchState(
            stall_min=25,
            cost_step=50,
            known_sha="aaa111",
            known_block_id="2026-07-19T07:00:00.000Z",
            known_cost_bucket=1,
            started_at=NOW,
            quota_ceiling_tokens=0,
        )
        events = blind.observe(now=NOW + 60, sha="aaa111", block=burning, heartbeat_age_min=1)
        assert events == []

    def test_parked_queue_is_already_holding(self, state: WatchState, burning: dict) -> None:
        events = state.observe(
            now=NOW + 60, sha="aaa111", block=burning, heartbeat_age_min=1, parked=True
        )
        assert events == []
        assert state.quota_low_alerted_block == ""

    def test_empty_block_is_not_an_observation(self, state: WatchState) -> None:
        assert state.observe(now=NOW + 60, sha="aaa111", block={}, heartbeat_age_min=1) == []


class TestInitialStateAndProbeProjection:
    @pytest.fixture(autouse=True)
    def offline_gateways(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(watch_module, "base_branch_sha", lambda **kwargs: "aaa111")
        monkeypatch.setattr(
            watch_module,
            "blocks_report",
            lambda *, active_only: ok(
                {
                    "blocks": (
                        [
                            {
                                "id": "2026-07-19T07:00:00.000Z",
                                "isActive": True,
                                "costUSD": 60.0,
                                "totalTokens": 700_000,
                                "remainingMinutes": 120,
                                "burnRate": {"tokensPerMinute": 20_000},
                            }
                        ]
                        if active_only
                        else [{"id": "prior", "isActive": False, "totalTokens": 1_000_000}]
                    )
                }
            ),
        )

    def test_initial_state_infers_the_ceiling_from_history(self) -> None:
        state = watch_module.initial_watch_state(
            stall_min=25, cost_step=50, base_branch="develop", started_at=NOW
        )
        assert state.quota_ceiling_tokens == 1_000_000
        assert state.chunk_min == watch_module.DEFAULT_CHUNK_MIN

    def test_explicit_token_budget_overrides_history(self) -> None:
        state = watch_module.initial_watch_state(
            stall_min=25,
            cost_step=50,
            base_branch="develop",
            started_at=NOW,
            chunk_min=20,
            token_budget=2_000_000,
        )
        assert state.quota_ceiling_tokens == 2_000_000
        assert state.chunk_min == 20

    def test_probe_reports_the_burn_projection(self, tmp_path: Path) -> None:
        lines = watch_module.probe_lines(scratchpad=tmp_path, base_branch="develop")
        assert lines[1] == "burn: to_budget_min=15 ceiling_tokens=1000000 chunk_min=45"

    def test_probe_marks_an_unknowable_projection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            watch_module, "active_quota_block", lambda: {"id": "A", "costUSD": 1.0}
        )
        monkeypatch.setattr(watch_module, "historical_token_ceiling", lambda: 0)
        lines = watch_module.probe_lines(scratchpad=tmp_path, base_branch="develop")
        assert lines[1] == "burn: to_budget_min=? ceiling_tokens=unknown chunk_min=45"
