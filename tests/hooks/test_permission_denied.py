"""Tests for the PermissionDenied hook handler."""

from __future__ import annotations

import json

import pytest

from dev10x.domain.events.hook_input import HookRetry
from tests.fakers import BashHookInputFaker


class TestHookRetry:
    @pytest.fixture()
    def hook_retry(self) -> HookRetry:
        return HookRetry(message="Use Skill(Dev10x:git-commit) instead")

    def test_to_dict_decision(self, hook_retry: HookRetry) -> None:
        assert hook_retry.to_dict()["decision"] == "retry"

    def test_to_dict_message(self, hook_retry: HookRetry) -> None:
        assert hook_retry.to_dict()["message"] == "Use Skill(Dev10x:git-commit) instead"

    def test_emit_exits_zero(self, hook_retry: HookRetry) -> None:
        with pytest.raises(SystemExit) as exc_info:
            hook_retry.emit()
        assert exc_info.value.code == 0

    def test_emit_writes_json_to_stderr(
        self,
        hook_retry: HookRetry,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit):
            hook_retry.emit()
        output = json.loads(capsys.readouterr().err)
        assert output["hookSpecificOutput"]["hookEventName"] == "PermissionDenied"
        assert output["hookSpecificOutput"]["retry"] is True
        assert output["systemMessage"] == "Use Skill(Dev10x:git-commit) instead"

    def test_emit_omits_system_message_when_empty(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        retry = HookRetry(message="")
        with pytest.raises(SystemExit):
            retry.emit()
        output = json.loads(capsys.readouterr().err)
        assert "systemMessage" not in output

    def test_frozen(self, hook_retry: HookRetry) -> None:
        with pytest.raises(AttributeError):
            hook_retry.message = "changed"  # type: ignore[misc]


class TestSkillRedirectCorrect:
    @pytest.fixture()
    def validator(self):
        from dev10x.validators.skill_redirect import SkillRedirectValidator

        return SkillRedirectValidator()

    def test_returns_retry_for_git_commit(self, validator) -> None:
        inp = BashHookInputFaker.build(
            command='git commit -m "Enable feature X"',
        )
        result = validator.correct(inp=inp)
        assert result is not None
        assert isinstance(result, HookRetry)
        assert "Dev10x:git-commit" in result.message

    def test_returns_none_for_allowed_commit(self, validator) -> None:
        inp = BashHookInputFaker.build(
            command="git commit -F /tmp/Dev10x/git/commit-msg.abc123.txt",
        )
        result = validator.correct(inp=inp)
        assert result is None

    def test_returns_none_for_unmatched_command(self, validator) -> None:
        inp = BashHookInputFaker.build(command="git status")
        assert validator.should_run(inp=inp) is False

    def test_returns_retry_for_gh_pr_create(self, validator) -> None:
        inp = BashHookInputFaker.build(
            command="gh pr create --title 'test'",
        )
        result = validator.correct(inp=inp)
        assert result is not None
        assert isinstance(result, HookRetry)

    def test_returns_retry_for_git_push(self, validator) -> None:
        inp = BashHookInputFaker.build(command="git push origin main")
        result = validator.correct(inp=inp)
        assert result is not None
        assert isinstance(result, HookRetry)


class TestPrefixFrictionCorrect:
    @pytest.fixture()
    def validator(self):
        from dev10x.validators.prefix_friction import PrefixFrictionValidator

        return PrefixFrictionValidator()

    def test_returns_retry_for_env_prefix_git(self, validator) -> None:
        inp = BashHookInputFaker.build(
            command="GIT_SEQUENCE_EDITOR=true git rebase -i HEAD~3",
        )
        result = validator.correct(inp=inp)
        assert result is not None
        assert isinstance(result, HookRetry)
        assert "ENV=value" in result.message or "env-var" in result.message.lower()

    def test_returns_retry_for_merge_base(self, validator) -> None:
        inp = BashHookInputFaker.build(
            command="git log $(git merge-base develop HEAD)..HEAD",
        )
        result = validator.correct(inp=inp)
        assert result is not None
        assert isinstance(result, HookRetry)
        assert "alias" in result.message.lower()

    def test_returns_none_for_clean_command(self, validator) -> None:
        inp = BashHookInputFaker.build(command="git status")
        assert validator.should_run(inp=inp) is False


class TestCorrectorProtocol:
    def test_skill_redirect_is_corrector(self) -> None:
        from dev10x.validators.base import Corrector
        from dev10x.validators.skill_redirect import SkillRedirectValidator

        assert isinstance(SkillRedirectValidator(), Corrector)

    def test_prefix_friction_is_corrector(self) -> None:
        from dev10x.validators.base import Corrector
        from dev10x.validators.prefix_friction import PrefixFrictionValidator

        assert isinstance(PrefixFrictionValidator(), Corrector)

    def test_non_corrector_validator_is_not_corrector(self) -> None:
        from dev10x.validators.base import Corrector
        from dev10x.validators.execution_safety import ExecutionSafetyValidator

        assert not isinstance(ExecutionSafetyValidator(), Corrector)
