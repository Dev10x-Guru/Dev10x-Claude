"""Tests for SafeSubshellValidator."""

from __future__ import annotations

import pytest

from dev10x.domain import HookAllow
from dev10x.validators.safe_subshell import SafeSubshellValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(
        command=command,
    )


class TestShouldRun:
    @pytest.fixture()
    def validator(self) -> SafeSubshellValidator:
        return SafeSubshellValidator()

    def test_true_when_subshell_present(self, validator: SafeSubshellValidator) -> None:
        inp = _make_input(command='basename "$(git rev-parse --show-toplevel)"')
        assert validator.should_run(inp=inp) is True

    def test_false_without_subshell(self, validator: SafeSubshellValidator) -> None:
        inp = _make_input(command="git status")
        assert validator.should_run(inp=inp) is False


class TestAutoApproval:
    @pytest.fixture()
    def validator(self) -> SafeSubshellValidator:
        return SafeSubshellValidator()

    @pytest.mark.parametrize(
        "command",
        [
            'basename "$(git rev-parse --show-toplevel)"',
            "echo $(git symbolic-ref --short HEAD)",
            "echo $(git rev-parse --short HEAD)",
            'basename "$(git config --get remote.origin.url)"',
            'dirname "$(git rev-parse --show-toplevel)"',
            "echo $(git describe --tags)",
            "echo \"$(git log --format='%(refname:short)')\"",
        ],
    )
    def test_approves_safe_outer_with_safe_subshell(
        self,
        validator: SafeSubshellValidator,
        command: str,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert isinstance(result, HookAllow)

    @pytest.mark.parametrize(
        "command",
        [
            'rm -rf "$(git rev-parse --show-toplevel)"',
            'git checkout "$(git rev-parse --short HEAD)"',
        ],
    )
    def test_no_opinion_on_unsafe_outer_command(
        self,
        validator: SafeSubshellValidator,
        command: str,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None

    @pytest.mark.parametrize(
        "command",
        [
            'basename "$(git push origin main)"',
            'echo "$(git reset --hard HEAD~1)"',
            "echo $(rm -rf /tmp)",
        ],
    )
    def test_no_opinion_on_unsafe_subshell(
        self,
        validator: SafeSubshellValidator,
        command: str,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None

    def test_no_opinion_without_subshells(self, validator: SafeSubshellValidator) -> None:
        inp = _make_input(command="git status")
        result = validator.validate(inp=inp)
        assert result is None

    def test_quoted_subshell_literal_is_ignored(self, validator: SafeSubshellValidator) -> None:
        # GH-309: $(...) inside single quotes is inert literal text. The
        # validator must not see it as a subshell at all.
        inp = _make_input(command="echo 'use $(date) for now'")
        assert validator.should_run(inp=inp) is False
        assert validator.validate(inp=inp) is None
