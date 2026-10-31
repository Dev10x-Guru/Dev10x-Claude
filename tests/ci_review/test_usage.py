from __future__ import annotations

from typing import Any

import pytest

from dev10x.ci_review.usage import usage_report

_EXECUTION: list[dict[str, Any]] = [
    {"type": "system", "subtype": "init"},
    {"type": "result", "total_cost_usd": 9.0},
    {
        "type": "result",
        "total_cost_usd": 0.12345,
        "num_turns": 7,
        "permission_denials": [{"tool": "Bash"}],
        "modelUsage": {
            "claude-sonnet": {
                "inputTokens": 10,
                "cacheCreationInputTokens": 200,
                "cacheReadInputTokens": 3000,
                "outputTokens": 40,
                "costUSD": 0.11115,
            },
            "claude-haiku": {"inputTokens": 5, "costUSD": 1},
        },
    },
]

_TABLE = (
    "### Claude usage\n\n"
    "| Model | Input | Cache write | Cache read | Output | Cost (USD) |\n"
    "|---|---:|---:|---:|---:|---:|\n"
    "| claude-sonnet | 10 | 200 | 3000 | 40 | 0.1112 |\n"
    "| claude-haiku | 5 | 0 | 0 | 0 | 1 |\n\n"
)


@pytest.mark.parametrize(
    ("notional", "suffix"),
    [(False, ""), (True, " (notional — OAuth subscription)")],
)
def test_report_matches_the_workflow_jq(notional: bool, suffix: str) -> None:
    report = usage_report(execution=_EXECUTION, notional=notional)

    assert report == (
        _TABLE
        + f"**Total:** $0.12 · 7 turns · 1 permission denials{suffix}\n\n"
        + "::notice title=Claude usage::$0.12345 · 7 turns · cache read 3000"
        + f" · cache write 200 · uncached input 15{suffix}\n"
    )


def test_no_result_reports_zeros() -> None:
    report = usage_report(execution=[], notional=False)

    assert "**Total:** $0 · 0 turns · 0 permission denials\n" in report
    assert report.endswith("cache read 0 · cache write 0 · uncached input 0\n")
