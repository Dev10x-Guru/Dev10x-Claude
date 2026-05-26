"""Tests for PipelineAllowValidator (DX011)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.domain import HookAllow
from dev10x.validators.pipeline_allow import PipelineAllowValidator
from tests.fakers import BashHookInputFaker


def _input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(command=command)


@pytest.fixture()
def validator() -> PipelineAllowValidator:
    return PipelineAllowValidator()


@pytest.fixture()
def fake_allow_patterns() -> Iterator[None]:
    patterns = [
        "uv run",
        "tail",
        "head",
        "wc",
        "git",
        "grep",
        "cat",
        "rg",
    ]
    with patch(
        "dev10x.validators.pipeline_allow._load_all_allow_patterns",
        return_value=patterns,
    ):
        yield


class TestShouldRun:
    @pytest.mark.parametrize(
        "command",
        [
            "uv run dev10x permission doctor | tail -20",
            "git log --oneline | head",
            "cat file.txt | grep error | wc -l",
        ],
    )
    def test_true_for_pipelines(self, validator: PipelineAllowValidator, command: str) -> None:
        assert validator.should_run(inp=_input(command=command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "ls -la",
            "echo hello",
        ],
    )
    def test_false_without_pipe(self, validator: PipelineAllowValidator, command: str) -> None:
        assert validator.should_run(inp=_input(command=command)) is False

    @pytest.mark.parametrize(
        "command",
        [
            "git status && git log | tail",
            "git status ; git log | tail",
            "git log | grep foo || echo none",
            "git log | tail && echo done",
        ],
    )
    def test_false_with_chaining_operators(
        self, validator: PipelineAllowValidator, command: str
    ) -> None:
        assert validator.should_run(inp=_input(command=command)) is False

    @pytest.mark.parametrize(
        "command",
        [
            "diff <(sort a) <(sort b) | head",
            "cat >(grep foo) | tail",
        ],
    )
    def test_false_with_process_substitution(
        self, validator: PipelineAllowValidator, command: str
    ) -> None:
        assert validator.should_run(inp=_input(command=command)) is False

    def test_false_with_command_substitution(self, validator: PipelineAllowValidator) -> None:
        cmd = "echo $(git rev-parse HEAD) | tail"
        assert validator.should_run(inp=_input(command=cmd)) is False

    def test_false_with_backquote_substitution(self, validator: PipelineAllowValidator) -> None:
        cmd = "echo `git rev-parse HEAD` | tail"
        assert validator.should_run(inp=_input(command=cmd)) is False

    def test_false_with_trailing_background(self, validator: PipelineAllowValidator) -> None:
        cmd = "git log | tail -20 &"
        assert validator.should_run(inp=_input(command=cmd)) is False


@pytest.mark.usefixtures("fake_allow_patterns")
class TestValidateAutoApproval:
    def test_approves_simple_pipeline(self, validator: PipelineAllowValidator) -> None:
        cmd = "git log --oneline | tail -20"
        result = validator.validate(inp=_input(command=cmd))
        assert isinstance(result, HookAllow)

    def test_approves_pipeline_with_stderr_redirect(
        self, validator: PipelineAllowValidator
    ) -> None:
        cmd = "uv run dev10x permission doctor canonicalize --dry-run 2>&1 | tail -20"
        result = validator.validate(inp=_input(command=cmd))
        assert isinstance(result, HookAllow)

    def test_approves_pipeline_with_devnull_redirect(
        self, validator: PipelineAllowValidator
    ) -> None:
        cmd = "uv run flake8 tests/pages/crm.py 2>/dev/null | tail -20"
        result = validator.validate(inp=_input(command=cmd))
        assert isinstance(result, HookAllow)

    def test_approves_three_segment_pipeline(self, validator: PipelineAllowValidator) -> None:
        cmd = "cat file.txt | grep error | wc -l"
        result = validator.validate(inp=_input(command=cmd))
        assert isinstance(result, HookAllow)

    def test_includes_advisory_message(self, validator: PipelineAllowValidator) -> None:
        cmd = "git log | tail"
        result = validator.validate(inp=_input(command=cmd))
        assert isinstance(result, HookAllow)
        assert "DX011" in result.message


@pytest.mark.usefixtures("fake_allow_patterns")
class TestValidateNoOpinion:
    def test_no_opinion_when_segment_unmatched(self, validator: PipelineAllowValidator) -> None:
        cmd = "kubectl get pods | tail -5"
        assert validator.validate(inp=_input(command=cmd)) is None

    def test_no_opinion_when_last_segment_unmatched(
        self, validator: PipelineAllowValidator
    ) -> None:
        cmd = "git log | jq ."
        assert validator.validate(inp=_input(command=cmd)) is None

    def test_no_opinion_when_xargs_in_segment(self, validator: PipelineAllowValidator) -> None:
        cmd = "git log --format=%H | xargs git show"
        assert validator.validate(inp=_input(command=cmd)) is None

    def test_no_opinion_when_tee_in_segment(self, validator: PipelineAllowValidator) -> None:
        cmd = "git log | tee /tmp/log.txt"
        assert validator.validate(inp=_input(command=cmd)) is None

    def test_no_opinion_for_single_segment(self, validator: PipelineAllowValidator) -> None:
        cmd = "git log"
        assert validator.validate(inp=_input(command=cmd)) is None

    def test_no_opinion_when_segment_strips_to_empty(
        self, validator: PipelineAllowValidator
    ) -> None:
        cmd = ">/tmp/out | tail"
        assert validator.validate(inp=_input(command=cmd)) is None


class TestNoAllowRules:
    def test_no_opinion_when_settings_empty(
        self, validator: PipelineAllowValidator, tmp_path: Path
    ) -> None:
        with patch(
            "dev10x.validators.pipeline_allow._load_all_allow_patterns",
            return_value=[],
        ):
            cmd = "git log | tail"
            assert validator.validate(inp=_input(command=cmd)) is None
