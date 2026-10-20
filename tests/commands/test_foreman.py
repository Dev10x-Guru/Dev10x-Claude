from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.foreman import foreman


@pytest.fixture
def scratchpad(tmp_path: Path) -> Path:
    pad = tmp_path / "run"
    pad.mkdir()
    (pad / "status-m1.md").write_text("- 00:00 setup: branched\n", encoding="utf-8")
    return pad


@pytest.fixture(autouse=True)
def observation_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    import dev10x.skills.foreman.watch as watch

    monkeypatch.setattr(
        watch,
        "active_quota_block",
        lambda: {"id": "2026-07-19T07:00:00.000Z", "costUSD": 12.0},
    )
    monkeypatch.setattr(
        watch,
        "base_branch_sha",
        lambda *, base_branch, repo=None: "abc1234",
    )
    # Never read the real transcript history from a unit test — the
    # inferred ceiling would vary per machine (GH-979).
    monkeypatch.setattr(watch, "historical_token_ceiling", lambda: 0)


def test_probe_reports_quota_base_and_heartbeats(scratchpad: Path) -> None:
    result = CliRunner().invoke(foreman, ["probe", "--scratchpad", str(scratchpad)])
    assert result.exit_code == 0
    assert "quota: block=2026-07-19T07:00:00.000Z cost=$12" in result.output
    assert "base origin/develop: abc1234" in result.output
    assert "heartbeat: status-m1.md" in result.output


def test_probe_reports_missing_heartbeats(tmp_path: Path) -> None:
    result = CliRunner().invoke(foreman, ["probe", "--scratchpad", str(tmp_path)])
    assert result.exit_code == 0
    assert "heartbeat: no status files yet" in result.output


def test_watch_arms_and_stays_quiet_on_calm_rounds(
    scratchpad: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dev10x.commands.foreman as commands

    monkeypatch.setattr(commands.time, "sleep", lambda seconds: None)
    result = CliRunner().invoke(
        foreman,
        [
            "watch",
            "--scratchpad",
            str(scratchpad),
            "--max-rounds",
            "2",
            "--interval-s",
            "0",
        ],
    )
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "armed: base=origin/develop@abc1234 block=2026-07-19T07:00:00.000Z "
        "parked=no quota_ceiling_tokens=unknown"
    ]


def test_probe_reports_parked_and_own_merge_contracts(scratchpad: Path) -> None:
    (scratchpad / "parked").write_text("hold\n", encoding="utf-8")
    (scratchpad / "merged-shas").write_text("abc1234\ndef5678\n", encoding="utf-8")
    result = CliRunner().invoke(foreman, ["probe", "--scratchpad", str(scratchpad)])
    assert result.exit_code == 0
    assert "parked: yes own-merge shas: 2" in result.output


def test_watch_mutes_own_merge_base_movement(
    scratchpad: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dev10x.commands.foreman as commands
    import dev10x.skills.foreman.watch as watch

    (scratchpad / "merged-shas").write_text("def5678\n", encoding="utf-8")
    shas = iter(["abc1234", "def5678abc", "def5678abc"])
    monkeypatch.setattr(watch, "base_branch_sha", lambda *, base_branch, repo=None: next(shas))
    monkeypatch.setattr(commands.time, "sleep", lambda seconds: None)
    result = CliRunner().invoke(
        foreman,
        [
            "watch",
            "--scratchpad",
            str(scratchpad),
            "--max-rounds",
            "2",
            "--interval-s",
            "0",
        ],
    )
    assert result.exit_code == 0
    assert "BASE MOVED" not in result.output


def test_watch_arm_line_reports_parked_state(
    scratchpad: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dev10x.commands.foreman as commands

    (scratchpad / "parked").write_text("hold\n", encoding="utf-8")
    monkeypatch.setattr(commands.time, "sleep", lambda seconds: None)
    result = CliRunner().invoke(
        foreman,
        [
            "watch",
            "--scratchpad",
            str(scratchpad),
            "--max-rounds",
            "1",
            "--interval-s",
            "0",
        ],
    )
    assert result.exit_code == 0
    assert "parked=yes" in result.output


def test_probe_reports_the_burn_projection(scratchpad: Path) -> None:
    result = CliRunner().invoke(foreman, ["probe", "--scratchpad", str(scratchpad)])
    assert result.exit_code == 0
    assert "burn: to_budget_min=? ceiling_tokens=unknown chunk_min=45" in result.output


def test_watch_emits_quota_low_before_the_wall(
    scratchpad: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dev10x.commands.foreman as commands
    import dev10x.skills.foreman.watch as watch

    monkeypatch.setattr(
        watch,
        "active_quota_block",
        lambda: {
            "id": "2026-07-19T07:00:00.000Z",
            "costUSD": 12.0,
            "totalTokens": 900_000,
            "remainingMinutes": 90,
            "burnRate": {"tokensPerMinute": 20_000},
        },
    )
    monkeypatch.setattr(commands.time, "sleep", lambda seconds: None)
    result = CliRunner().invoke(
        foreman,
        [
            "watch",
            "--scratchpad",
            str(scratchpad),
            "--token-budget",
            "1000000",
            "--chunk-min",
            "45",
            "--max-rounds",
            "2",
            "--interval-s",
            "0",
        ],
    )
    assert result.exit_code == 0
    assert "quota_ceiling_tokens=1000000" in result.output
    assert "QUOTA LOW: ~5 min of block budget left at current burn" in result.output
    # Once per block, not once per round.
    assert result.output.count("QUOTA LOW:") == 1


def test_watch_stays_quiet_on_a_finished_worker(
    scratchpad: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dev10x.commands.foreman as commands

    # GH-1577: a DONE worker never writes again, so its mtime only ages;
    # it must not re-alarm every stall window.
    finished = scratchpad / "status-m1.md"
    finished.write_text("- 2026-10-10T23:29:54Z DONE: PR #1575 green\n", encoding="utf-8")
    os.utime(finished, (0, 0))
    monkeypatch.setattr(commands.time, "sleep", lambda seconds: None)
    result = CliRunner().invoke(
        foreman,
        ["watch", "--scratchpad", str(scratchpad), "--max-rounds", "2", "--interval-s", "0"],
    )
    assert result.exit_code == 0
    assert "STALL" not in result.output


def test_retire_records_the_chunk_without_touching_its_heartbeat(scratchpad: Path) -> None:
    before = (scratchpad / "status-m1.md").stat().st_mtime
    result = CliRunner().invoke(foreman, ["retire", "--scratchpad", str(scratchpad), "m1"])
    assert result.exit_code == 0
    assert result.output == "retired: status-m1.md\n"
    assert (scratchpad / "retired").read_text(encoding="utf-8") == "status-m1.md\n"
    assert (scratchpad / "status-m1.md").stat().st_mtime == before


def test_retire_refuses_an_unknown_chunk(scratchpad: Path) -> None:
    result = CliRunner().invoke(foreman, ["retire", "--scratchpad", str(scratchpad), "m9"])
    assert result.exit_code == 1
    assert "no heartbeat file status-m9.md" in result.output
    assert not (scratchpad / "retired").exists()


def test_escalate_appends_the_line_last(scratchpad: Path) -> None:
    path = scratchpad / "escalations-foreman.md"
    path.write_text("- MERGE REQUEST B1: PR #1\n", encoding="utf-8")
    result = CliRunner().invoke(
        foreman,
        ["escalate", "--scratchpad", str(scratchpad), "MERGE REQUEST B2: PR #2"],
    )
    assert result.exit_code == 0
    assert result.output == "escalated: escalations-foreman.md\n"
    assert path.read_text(encoding="utf-8").splitlines()[-1] == "- MERGE REQUEST B2: PR #2"


def test_escalate_refuses_a_line_the_watcher_ignores(scratchpad: Path) -> None:
    result = CliRunner().invoke(
        foreman,
        ["escalate", "--scratchpad", str(scratchpad), "--role", "crew", "just a note"],
    )
    assert result.exit_code == 1
    assert "must open with one of" in result.output
    assert not (scratchpad / "escalations-crew.md").exists()


def test_watch_delivers_a_mid_file_insert_and_drops_a_merged_request(
    scratchpad: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dev10x.commands.foreman as commands

    # GH-1582: the PLG night-run file order — each new request inserted
    # above the older ones — with B2 (#1575) already merged.
    path = scratchpad / "escalations-foreman.md"
    path.write_text(
        "- PROBE-DONE\n- MERGE REQUEST B1: PR #1573\n- MERGE REQUEST B2: PR #1575\n",
        encoding="utf-8",
    )
    (scratchpad / "merged-shas").write_text("abc1234  # PR #1575\n", encoding="utf-8")

    def insert_then_sleep(seconds: float) -> None:
        path.write_text(
            "- PROBE-DONE\n"
            "- MERGE REQUEST B1: PR #1573\n"
            "- MERGE REQUEST B4: PR #1576\n"
            "- MERGE REQUEST B3: PR #1575\n"
            "- MERGE REQUEST B2: PR #1575\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(commands.time, "sleep", insert_then_sleep)
    result = CliRunner().invoke(
        foreman,
        ["watch", "--scratchpad", str(scratchpad), "--max-rounds", "2", "--interval-s", "0"],
    )
    assert result.exit_code == 0
    assert result.output.splitlines()[1:] == ["MERGE REQUEST B4: PR #1576"]


def test_probe_flags_a_retired_heartbeat(scratchpad: Path) -> None:
    (scratchpad / "retired").write_text("m1\n", encoding="utf-8")
    result = CliRunner().invoke(foreman, ["probe", "--scratchpad", str(scratchpad)])
    assert result.exit_code == 0
    assert "heartbeat: status-m1.md retired age=" in result.output


def test_watch_emits_base_movement(scratchpad: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import dev10x.commands.foreman as commands
    import dev10x.skills.foreman.watch as watch

    shas = iter(["abc1234", "def5678", "def5678"])
    monkeypatch.setattr(watch, "base_branch_sha", lambda *, base_branch, repo=None: next(shas))
    monkeypatch.setattr(commands.time, "sleep", lambda seconds: None)
    result = CliRunner().invoke(
        foreman,
        [
            "watch",
            "--scratchpad",
            str(scratchpad),
            "--max-rounds",
            "2",
            "--interval-s",
            "0",
        ],
    )
    assert result.exit_code == 0
    assert "BASE MOVED: abc1234 -> def5678" in result.output
