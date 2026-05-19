"""Tests for BashAggregationValidator."""

from __future__ import annotations

import pytest

from dev10x.validators.bash_aggregation import BashAggregationValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(command=command)


class TestBashAggregationValidator:
    @pytest.fixture()
    def validator(self) -> BashAggregationValidator:
        return BashAggregationValidator()

    @pytest.mark.parametrize(
        "command",
        [
            "for d in src/*/; do ls $d; done",
            'for d in src/*/; do n=$(basename "$d"); echo "$n"; done | sort -rn',
            "while read line; do echo $line; done < file.txt",
            "until [ -f /tmp/ready ]; do sleep 1; done",
        ],
    )
    def test_blocks_loops(self, validator: BashAggregationValidator, command: str) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert "serialized commands" in result.message

    def test_blocks_nested_command_substitution(self, validator: BashAggregationValidator) -> None:
        inp = _make_input(command='echo "$(basename $(git rev-parse HEAD))"')
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_three_or_more_chained_statements(
        self, validator: BashAggregationValidator
    ) -> None:
        inp = _make_input(command="echo a; echo b; echo c")
        result = validator.validate(inp=inp)
        assert result is not None

    @pytest.mark.parametrize(
        "command",
        [
            "ls src/",
            "wc -l src/foo.py",
            "git status",
            "echo hello; echo world",
            'echo "$(git rev-parse HEAD)"',
            "if [ -f file ]; then echo yes; fi",
            "grep 'for x in y' file.txt",
            "grep -E 'while.*do' README.md",
        ],
    )
    def test_allows_safe_commands(self, validator: BashAggregationValidator, command: str) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None

    def test_should_run_short_circuits_on_simple_command(
        self, validator: BashAggregationValidator
    ) -> None:
        inp = _make_input(command="ls -la")
        assert validator.should_run(inp=inp) is False

    @pytest.mark.parametrize(
        "command",
        [
            "for d in *; do ls $d; done",
            "while true; do sleep 1; done",
            "echo a; echo b",
            'echo "$(date)"',
        ],
    )
    def test_should_run_true_for_aggregation_shapes(
        self, validator: BashAggregationValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        assert validator.should_run(inp=inp) is True
