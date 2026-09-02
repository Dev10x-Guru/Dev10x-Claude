"""ci_check_status waits out named advisory legs (GH-1138)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from dev10x.skills.monitor.ci_check_status import (
    compute_verdict,
    is_terminal,
    unsettled_named_checks,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_HOOKS = _REPO_ROOT / "hooks" / "hooks.json"
_MAP = _REPO_ROOT / "src" / "dev10x" / "validators" / "command-skill-map.yaml"

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


def test_monitor_is_on_the_bash_validator_chain():
    """A loop routed through Monitor to dodge the Bash hook is seen too."""
    hooks = json.loads(_HOOKS.read_text())
    pre = hooks["hooks"]["PreToolUse"]
    monitor = next(entry for entry in pre if entry["matcher"] == "Monitor")
    bash = next(entry for entry in pre if entry["matcher"] == "Bash")
    assert monitor["hooks"][0]["command"] == bash["hooks"][0]["command"]


@pytest.mark.parametrize("rule_name", ["ci-loop-handrolled", "watch-loop-handrolled"])
def test_loop_shapes_are_denied_not_advised(rule_name: str):
    data = yaml.safe_load(_MAP.read_text()) or {}
    rule = next(r for r in data["rules"] if r["name"] == rule_name)
    assert rule["hook_block"] is True
    assert rule["compensations"], "a blocking rule must name an executable fix"
