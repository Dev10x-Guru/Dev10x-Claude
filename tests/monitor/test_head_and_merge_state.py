"""A verdict names the head it was read for and whether it can merge (GH-1684).

Right after `gh pr update-branch` a wait returned the superseded head's
green, and over one PR's life it returned green four times while the PR
was BEHIND its base. Neither was visible in the payload, so every round
needed a separate read of the PR to tell a green from a mergeable one.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from dev10x.skills.monitor.ci_check_status import PrState, compute_verdict, get_pr_state

from dev10x.skills.monitor import ci_check_status as ci_check_status_module

_GREEN = [{"name": "lint", "bucket": "pass"}, {"name": "test", "bucket": "pass"}]
_SHA = "a" * 40


@pytest.fixture
def behind_result() -> dict:
    return compute_verdict(
        checks=_GREEN, mergeable="MERGEABLE", head_sha=_SHA, merge_state="BEHIND"
    )


def test_behind_green_reports_pending(behind_result: dict) -> None:
    assert behind_result["verdict"] == "pending"


def test_behind_green_carries_a_caveat(behind_result: dict) -> None:
    assert behind_result["verdict_caveat"].startswith("branch is behind its base")


def test_payload_reports_the_head_sha(behind_result: dict) -> None:
    assert behind_result["head_sha"] == _SHA


def test_payload_reports_the_merge_state(behind_result: dict) -> None:
    assert behind_result["merge_state"] == "BEHIND"


@pytest.mark.parametrize(
    ("checks", "merge_state"),
    [
        (_GREEN, "CLEAN"),
        ([{"name": "test", "bucket": "pending"}], "BEHIND"),
    ],
    ids=["green-and-clean", "pending-and-behind"],
)
def test_behind_caveat_absent_otherwise(checks: list[dict], merge_state: str) -> None:
    result = compute_verdict(checks=checks, merge_state=merge_state)

    assert "verdict_caveat" not in result


def test_draft_caveat_wins_over_behind() -> None:
    result = compute_verdict(
        checks=[{"name": "lint", "bucket": "pass"}, {"name": "test", "bucket": "skipping"}],
        is_draft=True,
        merge_state="BEHIND",
    )

    assert result["verdict_caveat"].startswith("draft PR:")


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (
            f'{{"mergeable": "MERGEABLE", "isDraft": false, "headRefOid": "{_SHA}",'
            ' "mergeStateStatus": "BEHIND"}',
            PrState(mergeable="MERGEABLE", head_sha=_SHA, merge_state="BEHIND"),
        ),
        (
            '{"mergeable": "MERGEABLE", "headRefOid": null, "mergeStateStatus": ""}',
            PrState(mergeable="MERGEABLE"),
        ),
    ],
    ids=["behind", "fields-missing"],
)
def test_get_pr_state_reads_head_and_merge_state(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    expected: PrState,
) -> None:
    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout)

    monkeypatch.setattr(ci_check_status_module.subprocess, "run", run)

    assert get_pr_state(pr_number=7, repo="o/r") == expected


@pytest.mark.parametrize(
    ("returncode", "stdout", "reason"),
    [(1, "", "exited 1"), (0, "not json", "non-JSON output")],
    ids=["gh-failure", "garbage"],
)
def test_an_unread_pr_state_says_so_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    returncode: int,
    stdout: str,
    reason: str,
) -> None:
    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=returncode, stdout=stdout)

    monkeypatch.setattr(ci_check_status_module.subprocess, "run", run)

    get_pr_state(pr_number=7, repo="o/r")

    assert reason in capsys.readouterr().err


@pytest.fixture
def head_moved_result(monkeypatch: pytest.MonkeyPatch) -> dict:
    states = iter(
        [
            PrState(mergeable="MERGEABLE", head_sha="b" * 40),
            PrState(mergeable="MERGEABLE", head_sha=_SHA),
        ]
    )
    monkeypatch.setattr(
        ci_check_status_module,
        "get_annotated_checks",
        lambda **_k: ci_check_status_module.ChecksRead(
            checks=list(_GREEN), source=ci_check_status_module.SOURCE_GH_CLI
        ),
    )
    monkeypatch.setattr(ci_check_status_module, "get_pr_state", lambda **_k: next(states))
    return ci_check_status_module.probe_once(pr_number=7, repo="o/r")


def test_a_head_moving_mid_read_reports_pending(head_moved_result: dict) -> None:
    assert head_moved_result["verdict"] == "pending"


def test_a_head_moving_mid_read_names_both_heads(head_moved_result: dict) -> None:
    assert head_moved_result["verdict_caveat"].startswith("head moved from bbbbbbbb to aaaaaaaa")


def test_probe_once_threads_head_and_merge_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ci_check_status_module,
        "get_annotated_checks",
        lambda **_k: ci_check_status_module.ChecksRead(
            checks=[{"name": "test", "bucket": "pending"}],
            source=ci_check_status_module.SOURCE_GH_CLI,
        ),
    )
    monkeypatch.setattr(
        ci_check_status_module,
        "get_pr_state",
        lambda **_k: PrState(mergeable="MERGEABLE", head_sha=_SHA, merge_state="BEHIND"),
    )

    result = ci_check_status_module.probe_once(pr_number=7, repo="o/r")

    assert (result["head_sha"], result["merge_state"]) == (_SHA, "BEHIND")
