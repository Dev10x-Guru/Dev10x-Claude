from __future__ import annotations

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
