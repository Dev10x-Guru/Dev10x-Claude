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


def test_probe_reports_quota_base_and_heartbeats(scratchpad: Path) -> None:
    result = CliRunner().invoke(foreman, ["probe", "--scratchpad", str(scratchpad)])
    assert result.exit_code == 0
    assert "quota: block=2026-07-19T07:00:00.000Z cost=$12" in result.output
    assert "base develop: abc1234" in result.output
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
    assert result.output.splitlines() == ["armed: base=abc1234 block=2026-07-19T07:00:00.000Z"]


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
