"""Tests for PrBaseValidator."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dev10x.validators.pr_base import PrBaseValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(
        command=command,
        raw={"tool_name": "Bash", "tool_input": {"command": command}},
    )


class TestShouldRun:
    @pytest.fixture()
    def validator(self) -> PrBaseValidator:
        return PrBaseValidator()

    def test_true_for_gh_pr_create(self, validator: PrBaseValidator) -> None:
        inp = _make_input(command="gh pr create --title 'My PR'")
        assert validator.should_run(inp=inp) is True

    def test_false_for_non_pr(self, validator: PrBaseValidator) -> None:
        inp = _make_input(command="gh issue list")
        assert validator.should_run(inp=inp) is False

    def test_false_for_search_naming_the_command(self, validator: PrBaseValidator) -> None:
        # GH-1214 finding 6: grepping the docs for a shape is not running
        # it, and demanding --base of a search blocks the audit.
        inp = _make_input(command="rg -n 'gh pr create --body-file' skills/")
        assert validator.should_run(inp=inp) is False

    def test_true_for_pipeline_into_gh_pr_create(self, validator: PrBaseValidator) -> None:
        # An unquoted pipe can still run the command — stay on.
        inp = _make_input(command="grep -l foo . | xargs gh pr create --title x")
        assert validator.should_run(inp=inp) is True


class TestValidate:
    @pytest.fixture()
    def validator(self) -> PrBaseValidator:
        return PrBaseValidator()

    @patch("dev10x.validators.pr_base._detect_base_branch", return_value="develop")
    def test_blocks_missing_base(self, mock_detect: object, validator: PrBaseValidator) -> None:
        inp = _make_input(command="gh pr create --title 'My PR'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "--base develop" in result.message

    @patch("dev10x.validators.pr_base._detect_base_branch", return_value="develop")
    def test_allows_correct_base(self, mock_detect: object, validator: PrBaseValidator) -> None:
        inp = _make_input(command="gh pr create --base develop --title 'My PR'")
        result = validator.validate(inp=inp)
        assert result is None

    @patch("dev10x.validators.pr_base._detect_base_branch", return_value="develop")
    def test_allows_force_override(self, mock_detect: object, validator: PrBaseValidator) -> None:
        inp = _make_input(command="gh pr create --force --title 'My PR'")
        result = validator.validate(inp=inp)
        assert result is None

    @patch("dev10x.validators.pr_base._detect_base_branch", return_value=None)
    def test_blocks_when_no_base_detected(
        self, mock_detect: object, validator: PrBaseValidator
    ) -> None:
        inp = _make_input(command="gh pr create --title 'My PR'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Cannot detect base branch" in result.message

    @patch("dev10x.validators.pr_base._detect_base_branch", return_value="main")
    def test_uses_detected_branch(self, mock_detect: object, validator: PrBaseValidator) -> None:
        inp = _make_input(command="gh pr create --base main --title 'My PR'")
        result = validator.validate(inp=inp)
        assert result is None
