"""A draft's skipped checks caveat the verdict instead of passing silently (GH-1604)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from dev10x.skills.monitor.ci_check_status import PrState, compute_verdict, get_pr_state

from dev10x.skills.monitor import ci_check_status as ci_check_status_module

_DRAFT_CHECKS = [
    {"name": "lint", "bucket": "pass"},
    {"name": "test", "bucket": "skipping"},
    {"name": "coverage", "bucket": "skipping"},
]


@pytest.fixture
def draft_result() -> dict:
    return compute_verdict(checks=_DRAFT_CHECKS, mergeable="MERGEABLE", is_draft=True)


def test_draft_with_skips_keeps_the_green_verdict(draft_result: dict):
    assert draft_result["verdict"] == "green"


def test_draft_with_skips_carries_a_caveat(draft_result: dict):
    assert draft_result["verdict_caveat"] == (
        "draft PR: 2 checks skipped — CI has not run them; mark ready to get a real verdict"
    )


def test_draft_flag_is_reported(draft_result: dict):
    assert draft_result["is_draft"] is True


@pytest.mark.parametrize(
    ("checks", "is_draft"),
    [
        (_DRAFT_CHECKS, False),
        ([{"name": "lint", "bucket": "pass"}], True),
    ],
    ids=["ready-pr-with-skips", "draft-without-skips"],
)
def test_caveat_absent_otherwise(checks: list[dict], is_draft: bool):
    result = compute_verdict(checks=checks, is_draft=is_draft)
    assert "verdict_caveat" not in result


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (
            0,
            '{"mergeable": "MERGEABLE", "isDraft": true}',
            PrState(mergeable="MERGEABLE", is_draft=True),
        ),
        (
            0,
            '{"mergeable": "CONFLICTING", "isDraft": false}',
            PrState(mergeable="CONFLICTING", is_draft=False),
        ),
        (0, '{"mergeable": ""}', PrState(mergeable="UNKNOWN", is_draft=False)),
        (0, "not json", PrState()),
        (1, "", PrState()),
    ],
    ids=["draft", "ready", "blank-mergeable", "garbage", "gh-failure"],
)
def test_get_pr_state_reads_mergeable_and_draft_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    expected: PrState,
):
    calls: list[list[str]] = []

    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=returncode, stdout=stdout)

    monkeypatch.setattr(ci_check_status_module.subprocess, "run", run)

    assert get_pr_state(pr_number=7, repo="o/r") == expected
    assert calls == [["gh", "pr", "view", "7", "--repo", "o/r", "--json", "mergeable,isDraft"]]


def test_probe_once_threads_draft_state_into_the_verdict(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ci_check_status_module,
        "get_annotated_checks",
        lambda **_k: ci_check_status_module.ChecksRead(
            checks=list(_DRAFT_CHECKS), source=ci_check_status_module.SOURCE_GH_CLI
        ),
    )
    monkeypatch.setattr(
        ci_check_status_module,
        "get_pr_state",
        lambda **_k: PrState(mergeable="MERGEABLE", is_draft=True),
    )

    result = ci_check_status_module.probe_once(pr_number=7, repo="o/r")

    assert result["verdict_caveat"].startswith("draft PR: 2 checks skipped")
