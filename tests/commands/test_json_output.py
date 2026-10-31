"""Tests for the single-channel JSON error helper."""

from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from dev10x.commands.json_output import fail_json
from dev10x.core.domain.common.result import ErrorResult, err


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("boom", {"error": "boom"}),
        (err("bad block", index=3), {"error": "bad block", "index": 3}),
    ],
)
def test_fail_json_prints_payload_and_exits_one(
    error: str | ErrorResult,
    expected: dict,
) -> None:
    @click.command()
    def command() -> None:
        fail_json(error=error)

    result = CliRunner().invoke(command, [])

    assert result.exit_code == 1
    assert json.loads(result.output) == expected
