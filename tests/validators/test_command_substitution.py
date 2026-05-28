"""Tests for CommandSubstitutionValidator."""

from __future__ import annotations

import pytest

from dev10x.validators.command_substitution import CommandSubstitutionValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(
        command=command,
    )


class TestCommandSubstitutionValidator:
    @pytest.fixture()
    def validator(self) -> CommandSubstitutionValidator:
        return CommandSubstitutionValidator()

    @pytest.mark.parametrize(
        "command",
        [
            'gh api -f body="$(cat /tmp/Dev10x/reply.txt)"',
            'git commit -m "$(cat /tmp/Dev10x/msg.txt)"',
            'gh pr create --body "$(cat /tmp/pr-body.md)"',
            "gh api --method POST repos/o/r/pulls/1/comments"
            ' -f body="$(cat /tmp/Dev10x/reply-2.txt)"',
        ],
    )
    def test_blocks_cat_substitution(
        self, validator: CommandSubstitutionValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert "file flag" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            "gh api -F body=@/tmp/Dev10x/reply.txt",
            "git commit -F /tmp/Dev10x/msg.txt",
            "gh pr create --body-file /tmp/pr-body.md",
            "cat /tmp/file.txt",
            'echo "$(git rev-parse HEAD)"',
            "basename $(git rev-parse --show-toplevel)",
            # GH-309: $(cat ...) inside single quotes is literal text, not a
            # subshell — must not block.
            "echo 'docs say: use $(cat file) for piping'",
            "gh api graphql -f query='{ node(id: \"$(cat foo)\") { id } }'",
        ],
    )
    def test_allows_safe_commands(
        self, validator: CommandSubstitutionValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None

    def test_should_run_true_when_cat_subshell(
        self, validator: CommandSubstitutionValidator
    ) -> None:
        inp = _make_input(command='gh api -f body="$(cat /tmp/file)"')
        assert validator.should_run(inp=inp) is True

    def test_should_run_false_without_cat_subshell(
        self, validator: CommandSubstitutionValidator
    ) -> None:
        inp = _make_input(command="gh api -F body=@/tmp/file")
        assert validator.should_run(inp=inp) is False
