"""Tests for PrefixFrictionValidator."""

from __future__ import annotations

import pytest

from dev10x.validators.prefix_friction import PrefixFrictionValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str, cwd: str = "") -> BashHookInputFaker:
    return BashHookInputFaker.build(
        command=command,
        cwd=cwd,
    )


class TestShouldRun:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_true_for_and_chaining(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="mkdir -p /tmp/foo && ls")
        assert validator.should_run(inp=inp) is True

    def test_true_for_env_prefix_git(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="GIT_SEQUENCE_EDITOR=true git rebase -i HEAD~3")
        assert validator.should_run(inp=inp) is True

    def test_true_for_merge_base(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git log $(git merge-base develop HEAD)..HEAD")
        assert validator.should_run(inp=inp) is True

    def test_true_for_git_c(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git -C /some/path log --oneline")
        assert validator.should_run(inp=inp) is True

    def test_true_for_rev_parse_toplevel(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command='cd "$(git rev-parse --show-toplevel)" && git status --short')
        assert validator.should_run(inp=inp) is True

    def test_false_for_simple_command(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git status")
        assert validator.should_run(inp=inp) is False


class TestCdRevparseChain:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_cd_revparse_with_quotes(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command='cd "$(git rev-parse --show-toplevel)" && git status --short')
        result = validator.validate(inp=inp)
        assert result is not None
        assert "unnecessary" in result.message
        assert "git status --short" in result.message

    def test_blocks_cd_revparse_without_quotes(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="cd $(git rev-parse --show-toplevel) && git status --short")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "unnecessary" in result.message

    def test_allows_standalone_revparse(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git rev-parse --show-toplevel")
        result = validator.validate(inp=inp)
        assert result is None


class TestGitCNoop:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_git_c_matching_cwd(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command="git -C /work/example/.worktrees/app-pos-4 log --oneline -5",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "redundant" in result.message
        assert "git log --oneline -5" in result.message

    def test_allows_git_c_different_path(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command="git -C /work/example/other-repo log --oneline",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_git_c_without_cwd(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git -C /some/path log --oneline")
        result = validator.validate(inp=inp)
        assert result is None

    def test_blocks_with_trailing_slash_normalization(
        self, validator: PrefixFrictionValidator
    ) -> None:
        inp = _make_input(
            command="git -C /work/example/.worktrees/app-pos-4/ add src/file.py",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_git_c_with_quoted_path(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command='git -C "/work/example/.worktrees/app-pos-4" log --oneline -5',
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "redundant" in result.message


class TestCdNoopChain:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_cd_matching_cwd_with_env_git(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command=(
                "cd /work/example/.worktrees/app-pos-4 && "
                "GIT_SEQUENCE_EDITOR=true git develop-rebase --autosquash"
            ),
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "redundant" in result.message
        assert "GIT_SEQUENCE_EDITOR=true git develop-rebase --autosquash" in result.message

    def test_blocks_cd_to_different_path_with_git(
        self, validator: PrefixFrictionValidator
    ) -> None:
        inp = _make_input(
            command="cd /work/example/other-repo && git status",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "git -C" in result.message

    def test_blocks_cd_without_cwd_with_git(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="cd /some/path && git status")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "git -C" in result.message

    def test_blocks_cd_with_trailing_slash(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command="cd /work/example/.worktrees/app-pos-4/ && ls",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_cd_with_double_quoted_path(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command='cd "/work/example/.worktrees/app-pos-4" && git diff develop...HEAD --stat',
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "redundant" in result.message
        assert "git diff develop...HEAD --stat" in result.message

    def test_blocks_cd_with_single_quoted_path(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command="cd '/work/example/.worktrees/app-pos-4' && git status",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "redundant" in result.message


class TestCdGitChain:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_cd_different_path_and_git(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command="cd /work/example/other-repo && git push origin HEAD",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "git -C" in result.message
        assert "push origin HEAD" in result.message

    def test_blocks_cd_git_without_cwd(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="cd /some/path && git status")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "git -C" in result.message

    def test_blocks_cd_git_with_quoted_path(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command='cd "/work/example/other repo" && git log --oneline',
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "git -C" in result.message

    def test_cd_same_path_caught_by_noop_first(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command="cd /work/example/.worktrees/app-pos-4 && git push origin HEAD",
            cwd="/work/example/.worktrees/app-pos-4",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "redundant" in result.message

    def test_allows_cd_and_non_git_command(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(
            command="cd /some/path && ls -la",
            cwd="/work/somewhere-else",
        )
        result = validator.validate(inp=inp)
        assert result is None


class TestEnvPrefixGit:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_env_prefix_git(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="GIT_SEQUENCE_EDITOR=true git rebase -i HEAD~3")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "ENV=value prefix" in result.message

    def test_allows_plain_git(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git status")
        result = validator.validate(inp=inp)
        assert result is None


class TestMergeBase:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_merge_base_subshell(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git log $(git merge-base develop HEAD)..HEAD")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "merge-base" in result.message

    def test_suggests_alias(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git diff $(git merge-base develop HEAD)..HEAD")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "develop-diff" in result.message


class TestAndChaining:
    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_setup_and_path_based(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="mkdir -p /tmp/foo && ~/.claude/tools/script.sh arg1")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "&&" in result.message

    def test_allows_non_setup_and_chain(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git add file.py && git status")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_setup_without_path_based(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="mkdir -p /tmp/foo && ls /tmp/foo")
        result = validator.validate(inp=inp)
        assert result is None
