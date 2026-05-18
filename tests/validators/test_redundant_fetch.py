"""Tests for the redundant-fetch advisory validator (GH-206)."""

from __future__ import annotations

import pytest

from dev10x.domain import HookAllow, HookInput
from dev10x.validators.redundant_fetch import RedundantFetchValidator


def _make_input(*, command: str) -> HookInput:
    return HookInput(
        tool_name="Bash",
        command=command,
        raw={"tool_name": "Bash", "tool_input": {"command": command}},
        cwd="/cwd",
    )


@pytest.fixture
def validator() -> RedundantFetchValidator:
    return RedundantFetchValidator()


class TestContentsFetchAdvisory:
    def test_advises_on_gh_api_contents(self, validator: RedundantFetchValidator) -> None:
        cmd = (
            "gh api repos/Dev10x-Guru/Dev10x-Claude/contents/"
            "src/dev10x/validators/skill_redirect.py?ref=develop"
        )
        result = validator.validate(inp=_make_input(command=cmd))
        assert isinstance(result, HookAllow)
        assert "skill_redirect.py" in result.message
        assert "GH-206" in result.message

    def test_strips_query_string_from_path(self, validator: RedundantFetchValidator) -> None:
        cmd = "gh api repos/o/r/contents/path/file.py?ref=main"
        result = validator.validate(inp=_make_input(command=cmd))
        assert isinstance(result, HookAllow)
        assert "path/file.py" in result.message
        assert "?ref=main" not in result.message

    def test_should_run_true(self, validator: RedundantFetchValidator) -> None:
        cmd = "gh api repos/o/r/contents/x"
        assert validator.should_run(inp=_make_input(command=cmd)) is True

    def test_should_run_false_for_unrelated(self, validator: RedundantFetchValidator) -> None:
        assert validator.should_run(inp=_make_input(command="git status")) is False


class TestBase64UnwrapAdvisory:
    def test_advises_on_python_base64_b64decode(self, validator: RedundantFetchValidator) -> None:
        cmd = (
            "gh api repos/o/r/contents/x | python3 -c "
            '"import json,sys,base64; '
            "print(base64.b64decode(json.load(sys.stdin)['content']).decode())\""
        )
        result = validator.validate(inp=_make_input(command=cmd))
        assert isinstance(result, HookAllow)
        assert "base64" in result.message
        assert "GH-206" in result.message

    def test_advises_even_without_gh_api_in_command(
        self, validator: RedundantFetchValidator
    ) -> None:
        cmd = 'cat envelope.json | python3 -c "import base64; base64.b64decode(x)"'
        result = validator.validate(inp=_make_input(command=cmd))
        assert isinstance(result, HookAllow)

    def test_should_run_true_for_base64(self, validator: RedundantFetchValidator) -> None:
        assert validator.should_run(inp=_make_input(command="base64.b64decode(x)")) is True


class TestNonMatching:
    def test_plain_gh_pr_view_returns_none(self, validator: RedundantFetchValidator) -> None:
        cmd = "gh pr view 42 --json title,body"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is None

    def test_random_python_returns_none(self, validator: RedundantFetchValidator) -> None:
        cmd = "python3 -c 'print(1+1)'"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is None

    def test_advisory_never_blocks(self, validator: RedundantFetchValidator) -> None:
        """HookAllow means the command proceeds — never HookResult/deny."""
        cmd = "gh api repos/o/r/contents/x?ref=main"
        result = validator.validate(inp=_make_input(command=cmd))
        assert isinstance(result, HookAllow)
