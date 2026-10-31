"""ci_check_status waits out named advisory legs (GH-1138)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from dev10x.skills.monitor.ci_check_status import (
    compute_verdict,
    is_terminal,
    unsettled_named_checks,
)

from dev10x.core.config.hook_fragments import merged_hook_entries
from dev10x.core.config.loader import load_document
from dev10x.skills.monitor import ci_check_status as ci_check_status_module

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MAP = _REPO_ROOT / "src" / "dev10x" / "core" / "validators" / "command-skill-map.yaml"

_BOT_LEGS = ["claude-review", "hygiene-review"]


def _check(name: str, bucket: str, *, required: bool = False) -> dict[str, Any]:
    return {"name": name, "bucket": bucket, "required": required}


def _result(*checks: dict[str, Any]) -> dict:
    return compute_verdict(checks=list(checks))


@pytest.fixture
def fixup_cycle() -> dict:
    """The routine mid-review state: required red by design, bots pending."""
    return _result(
        _check("git-history-linting", "fail", required=True),
        _check("build", "pass", required=True),
        _check("claude-review", "pending"),
        _check("hygiene-review", "pending"),
    )


def test_required_failure_ends_the_wait_without_wait_for(fixup_cycle: dict):
    """The pre-GH-1138 behaviour — correct for a merge decision."""
    assert fixup_cycle["verdict"] == "failing"
    assert fixup_cycle["pending"] == 2
    assert is_terminal(result=fixup_cycle) is True


def test_wait_for_keeps_polling_past_a_red_required_check(fixup_cycle: dict):
    assert is_terminal(result=fixup_cycle, wait_for=_BOT_LEGS) is False


def test_wait_for_ends_once_named_legs_settle():
    result = _result(
        _check("git-history-linting", "fail", required=True),
        _check("claude-review", "pass"),
        _check("hygiene-review", "fail"),
    )
    assert is_terminal(result=result, wait_for=_BOT_LEGS) is True


@pytest.mark.parametrize("bucket", ["pass", "fail", "cancel", "skipping"])
def test_every_terminal_bucket_counts_as_settled(bucket: str):
    result = _result(_check("claude-review", bucket))
    assert unsettled_named_checks(result=result, wait_for=["claude-review"]) == []


def test_unregistered_named_check_is_unsettled():
    """A leg that has not appeared yet is what the caller is waiting for."""
    result = _result(_check("build", "pass", required=True))
    assert unsettled_named_checks(result=result, wait_for=_BOT_LEGS) == _BOT_LEGS


def test_conflicting_still_returns_immediately():
    """Nothing further will run — waiting for a bot leg is pointless."""
    result = compute_verdict(
        checks=[_check("claude-review", "pending")],
        mergeable="CONFLICTING",
    )
    assert is_terminal(result=result, wait_for=_BOT_LEGS) is True


def test_green_run_with_wait_for_still_waits_for_an_unregistered_leg():
    """wait_for is a floor, not a filter — an absent named leg keeps polling."""
    result = _result(_check("build", "pass", required=True))
    assert result["verdict"] == "green"
    assert is_terminal(result=result) is True
    assert is_terminal(result=result, wait_for=_BOT_LEGS) is False


@pytest.fixture
def fast_path_probes(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """GH-1609: required red on the first probe, bot legs settling on the third."""
    probes = [
        _result(
            _check("git-history-linting", "fail", required=True),
            _check("claude-review", "pending"),
            _check("hygiene-review", "pending"),
        ),
        _result(
            _check("git-history-linting", "fail", required=True),
            _check("claude-review", "pass"),
            _check("hygiene-review", "pending"),
        ),
        _result(
            _check("git-history-linting", "fail", required=True),
            _check("claude-review", "pass"),
            _check("hygiene-review", "pass"),
        ),
    ]
    served: list[dict] = []

    def probe(**_kwargs: Any) -> dict:
        result = probes[min(len(served), len(probes) - 1)]
        served.append(result)
        return result

    monkeypatch.setattr(ci_check_status_module, "probe_once", probe)
    monkeypatch.setattr(ci_check_status_module.time, "sleep", lambda *_a, **_k: None)
    return served


def test_fast_path_honours_wait_for_past_a_red_required_check(fast_path_probes: list[dict]):
    result = ci_check_status_module.poll_until_terminal(
        pr_number=1,
        repo="o/r",
        initial_wait=0,
        poll_interval=0,
        max_polls=5,
        wait_for=_BOT_LEGS,
    )

    assert len(fast_path_probes) == 3
    assert unsettled_named_checks(result=result, wait_for=_BOT_LEGS) == []


def test_monitor_is_on_the_bash_validator_chain():
    """A loop routed through Monitor to dodge the Bash hook is seen too."""
    commands = {
        matcher: command
        for event, matcher, command, _ in merged_hook_entries(plugin_root=_REPO_ROOT)
        if event == "PreToolUse"
    }
    assert commands["Monitor"] == commands["Bash"]


@pytest.mark.parametrize("rule_name", ["ci-loop-handrolled", "watch-loop-handrolled"])
def test_loop_shapes_are_denied_not_advised(rule_name: str):
    data = load_document(yaml_path=_MAP)
    rule = next(r for r in data["rules"] if r["name"] == rule_name)
    assert rule["hook_block"] is True
    assert rule["compensations"], "a blocking rule must name an executable fix"
