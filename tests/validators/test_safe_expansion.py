"""Tests for SafeExpansionValidator (GH-309)."""

from __future__ import annotations

import pytest

from dev10x.domain import HookAllow
from dev10x.validators.safe_expansion import SafeExpansionValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(command=command)


class TestSafeExpansionValidator:
    @pytest.fixture()
    def validator(self) -> SafeExpansionValidator:
        return SafeExpansionValidator()

    @pytest.mark.parametrize(
        "command",
        [
            # GH-271 evidence #13 — safe env var, double-quoted
            'echo "$CLAUDE_PLUGIN_ROOT"',
            # GH-271 evidence #20 — fixed ANSI-C escape
            "sort -t$'\\t' -k2 file",
            # GH-271 evidence #49/#51/#52/#54 — braces inside single-quoted GraphQL
            "gh api graphql -f query='query { viewer { login } }'",
            # GH-271 evidence #63 — safe env var, brace form
            "${CLAUDE_PLUGIN_ROOT}/skills/foo/scripts/db.sh",
            # GH-271 evidence #69 — bare safe env var
            "$CLAUDE_PLUGIN_ROOT/skills/foo/scripts/script.sh",
            # GH-271 evidence #88 — SvelteKit route-group parens in unquoted path
            "grep -rn pattern apps/web/routes/(app)/dashboard/",
            # Combinations
            "cp $HOME/.config/file ${CLAUDE_PLUGIN_ROOT}/dest",
            "echo $USER@$HOME",
        ],
    )
    def test_approves_inert_metacharacter_commands(
        self,
        validator: SafeExpansionValidator,
        command: str,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert isinstance(result, HookAllow), f"expected HookAllow for {command!r}, got {result!r}"

    @pytest.mark.parametrize(
        "command",
        [
            # Genuine command substitution — must NOT auto-approve
            'gh api -f body="$(cat /tmp/file)"',
            "echo $(rm -rf /)",
            # Backticks — must NOT auto-approve
            "echo `whoami`",
            # Unknown env var — must NOT auto-approve (could be anything)
            "echo $MYSTERY_VAR",
            "echo ${MYSTERY}",
            # Unquoted brace expansion — must NOT auto-approve (creates files)
            "touch file{1,2,3}.txt",
            # Unquoted subshell group — must NOT auto-approve
            "(cd /tmp && ls)",
        ],
    )
    def test_does_not_approve_genuine_threats(
        self,
        validator: SafeExpansionValidator,
        command: str,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None, f"expected None for {command!r}, got {result!r}"

    def test_should_run_true_for_metacharacter_commands(
        self,
        validator: SafeExpansionValidator,
    ) -> None:
        assert validator.should_run(inp=_make_input(command="echo $HOME")) is True
        assert validator.should_run(inp=_make_input(command="echo `date`")) is True
        assert validator.should_run(inp=_make_input(command="(ls)")) is True

    def test_should_run_false_for_plain_commands(
        self,
        validator: SafeExpansionValidator,
    ) -> None:
        assert validator.should_run(inp=_make_input(command="git status")) is False
        assert validator.should_run(inp=_make_input(command="ls -la /tmp")) is False
