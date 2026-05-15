from __future__ import annotations

import pytest

from dev10x.domain.hook_telemetry import HookOutcome, HookPhase


@pytest.mark.parametrize(
    "exit_code,expected",
    [
        (0, HookOutcome.OK),
        (2, HookOutcome.BLOCK),
        (1, HookOutcome.ERROR),
        (3, HookOutcome.UNKNOWN),
        (-1, HookOutcome.UNKNOWN),
        (137, HookOutcome.UNKNOWN),
    ],
)
def test_outcome_from_exit_code(exit_code: int, expected: HookOutcome) -> None:
    assert HookOutcome.from_exit_code(exit_code) is expected


def test_phase_values_match_jsonl_schema() -> None:
    assert HookPhase.BODY == "body"
    assert HookPhase.WRAP == "wrap"


def test_outcome_values_match_jsonl_schema() -> None:
    assert HookOutcome.OK == "ok"
    assert HookOutcome.BLOCK == "block"
    assert HookOutcome.ERROR == "error"
    assert HookOutcome.UNKNOWN == "unknown"
