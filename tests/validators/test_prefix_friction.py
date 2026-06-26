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


class TestGitCConfig:
    """Lowercase `git -c <key>=<value>` config-prefix block (GH-488 S19)."""

    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_should_run_for_git_c_config(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git -c core.pager=cat status --porcelain")
        assert validator.should_run(inp=inp) is True

    def test_blocks_pager_status(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git -c core.pager=cat status --porcelain")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "page" in result.message
        assert "git status --porcelain" in result.message
        assert "git nopager" in result.message

    def test_blocks_pager_branch(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git -c core.pager=cat branch --show-current")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "git branch --show-current" in result.message

    def test_blocks_hookspath_with_safety_message(
        self, validator: PrefixFrictionValidator
    ) -> None:
        inp = _make_input(command="git -c core.hooksPath=/dev/null diff --cached")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "hooks" in result.message
        assert "git diff --cached" in result.message

    def test_blocks_general_config_override(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git -c user.name=Bot commit -m wip")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "user.name" in result.message
        assert "git-alias-setup" in result.message

    def test_strips_multiple_c_flags_in_bare_command(
        self, validator: PrefixFrictionValidator
    ) -> None:
        inp = _make_input(command="git -c core.pager=cat -c color.ui=always status")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "git status" in result.message
        assert "-c " not in result.message.split("git status")[1]

    def test_blocks_color_ui(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git -c color.ui=never log --oneline")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "color" in result.message
        assert "git nocolor" in result.message
        assert "git log --oneline" in result.message

    def test_allows_nopager_alias(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git nopager status --short")
        assert validator.should_run(inp=inp) is False
        assert validator.validate(inp=inp) is None

    def test_allows_nocolor_alias(self, validator: PrefixFrictionValidator) -> None:
        inp = _make_input(command="git nocolor status --short")
        assert validator.should_run(inp=inp) is False
        assert validator.validate(inp=inp) is None

    def test_does_not_match_capital_c_directory_flag(
        self, validator: PrefixFrictionValidator
    ) -> None:
        # `git -C <dir>` (capital) is the directory flag, handled separately;
        # the config check must not fire on it.
        inp = _make_input(command="git -C /some/path log --oneline")
        assert validator._check_git_c_config(inp=inp) is None


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


class TestRedirectThenPositional:
    """GH-119: redirect followed by positional args bypasses prefix matching."""

    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_find_with_redirect_before_name(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(
            command='find /home/user/notes 2>/dev/null -name "*.md"',
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Redirect" in result.message
        assert "Move the redirect to the end" in result.message

    def test_blocks_find_with_stderr_to_stdout_before_args(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(command="find /opt/data 2>&1 -type f")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Redirect" in result.message

    def test_allows_redirect_at_end(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(command='find /home/user -name "*.md" 2>/dev/null')
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_find_with_pipe_only(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(command="find /opt/data -type f | head -10")
        result = validator.validate(inp=inp)
        assert result is None


class TestSemicolonChain:
    """GH-119: `;` chains break whole-command allow-rule matching."""

    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    def test_blocks_two_find_commands_chained(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(
            command="find /a -name x; find /b -name y",
        )
        result = validator.validate(inp=inp)
        assert result is not None
        assert "; ` chain" in result.message or ";" in result.message
        assert "separate Bash tool calls" in result.message

    def test_blocks_grep_then_find(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(command="grep foo /tmp/a.log; find /var/log -name 'b.log'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "separate Bash tool calls" in result.message

    def test_allows_single_command_with_trailing_args(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(command="find /home -name '*.py' -type f")
        result = validator.validate(inp=inp)
        assert result is None

    @pytest.mark.parametrize(
        "command",
        [
            "git status; git fetch",
            "git log -1; git diff HEAD~1",
            "gh pr view 1; gh pr checks 1",
            "pwd; whoami",
            "echo a; echo b",
            "uv run pytest; uv run ruff check",
            "docker ps; docker images",
            "kubectl get pods; kubectl get svc",
            "python3 -V; which python3",
            "env; printenv HOME",
        ],
    )
    def test_blocks_widened_chain_heads(
        self,
        validator: PrefixFrictionValidator,
        command: str,
    ) -> None:
        """GH-127 #5: widened head set catches documented nuisance chains."""
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert "separate Bash tool calls" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            # State-changing commands intentionally NOT widened.
            "rm a.txt; rm b.txt",
            "mkdir foo; cd foo",
            "mv a b; mv c d",
            "touch x; touch y",
        ],
    )
    def test_allows_state_changing_chains(
        self,
        validator: PrefixFrictionValidator,
        command: str,
    ) -> None:
        """State-changing chains stay out of scope — splitting would be
        more disruptive than helpful."""
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None


class TestShellLoopWrap:
    """GH-258: shell loops/xargs/find -exec wrap allowed commands."""

    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        return PrefixFrictionValidator()

    @pytest.mark.parametrize(
        ("command", "wrapper", "inner"),
        [
            (
                "for n in 169 170 171; do gh api repos/x/y/issues/$n; done",
                "for",
                "gh",
            ),
            (
                "while read line; do git log $line; done",
                "while",
                "git",
            ),
            (
                "until [ -z $x ]; do kubectl get pods; done",
                "until",
                "kubectl",
            ),
            (
                "echo a b c | xargs -I{} gh api {}",
                "xargs",
                "gh",
            ),
            (
                r"find . -name '*.py' -exec git log {} \;",
                "find -exec",
                "git",
            ),
        ],
    )
    def test_blocks_shell_loop_wrap(
        self,
        validator: PrefixFrictionValidator,
        command: str,
        wrapper: str,
        inner: str,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert wrapper in result.message
        assert inner in result.message
        assert "parallel Bash tool calls" in result.message

    def test_allows_loop_with_unrelated_body(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        # Loop bodies whose inner head is not in the allowed-tokens set
        # (e.g. plain `echo`) are out of scope — they're rarely the
        # source of the documented friction.
        inp = _make_input(command="for n in 1 2 3; do echo $n; done")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_xargs_with_unrelated_inner(
        self,
        validator: PrefixFrictionValidator,
    ) -> None:
        inp = _make_input(command="ls | xargs cat")
        result = validator.validate(inp=inp)
        assert result is None


class TestUvRunEnvFlagNormalization:
    """GH-485: strip `uv run` env-flags and approve when the inner command
    is independently allowed (inner tier governs)."""

    @pytest.fixture()
    def validator(self) -> PrefixFrictionValidator:
        v = PrefixFrictionValidator()
        v._allow_patterns = ["uv run pytest", "uv run mypy", "python manage.py", "pytest"]
        return v

    @pytest.mark.parametrize(
        "command",
        [
            "uv run --directory apps/api pytest tests/",
            "uv run --extra dev mypy src/",
            "uv run --directory apps/api python manage.py makemigrations core",
            "uv run --frozen --directory apps/api pytest",
            "uv run --directory=apps/api pytest tests/",
        ],
    )
    def test_should_run_true_for_uv_run_env_flags(
        self, validator: PrefixFrictionValidator, command: str
    ) -> None:
        assert validator.should_run(inp=_make_input(command=command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            # --with disqualifies (no env-flag normalization), and plain
            # `uv run <tool>` needs no normalization — neither should_run.
            "uv run --with httpx python manage.py shell",
            "uv run pytest tests/",
            "ls -la",
        ],
    )
    def test_should_run_false_when_no_normalization(
        self, validator: PrefixFrictionValidator, command: str
    ) -> None:
        assert validator.should_run(inp=_make_input(command=command)) is False

    @pytest.mark.parametrize(
        "command",
        [
            "uv run --directory apps/api pytest tests/test_foo.py",
            "uv run --extra dev mypy src/",
            "uv run --directory apps/api python manage.py makemigrations core",
            "uv run --frozen --directory apps/api pytest -k smoke",
            "uv run --directory=apps/api pytest tests/",
        ],
    )
    def test_inner_allowed_commands_auto_approved(
        self, validator: PrefixFrictionValidator, command: str
    ) -> None:
        from dev10x.domain import HookAllow

        result = validator.validate(inp=_make_input(command=command))
        assert isinstance(result, HookAllow)
        assert "DX007" in result.message

    def test_with_pkg_disqualifies_auto_approval(self, validator: PrefixFrictionValidator) -> None:
        # `--with httpx` installs an arbitrary package — never auto-approve;
        # falls through to the fence-tool ask (no HookAllow).
        result = validator.validate(
            inp=_make_input(command="uv run --with httpx python manage.py shell")
        )
        assert result is None

    def test_with_eq_form_disqualifies_auto_approval(
        self, validator: PrefixFrictionValidator
    ) -> None:
        result = validator.validate(inp=_make_input(command="uv run --with=httpx pytest tests/"))
        assert result is None

    def test_inner_ask_command_not_approved(self, validator: PrefixFrictionValidator) -> None:
        # `python -c ...` is not in the allow list — inner tier governs, so
        # no auto-approval; the command falls through to ask/deny.
        result = validator.validate(
            inp=_make_input(command="uv run --directory apps/api python -c 'import os'")
        )
        assert result is None

    def test_inner_denied_command_not_approved(self, validator: PrefixFrictionValidator) -> None:
        result = validator.validate(
            inp=_make_input(command="uv run --directory apps/api rm -rf /tmp/x")
        )
        assert result is None

    def test_plain_uv_run_without_env_flags_no_opinion(
        self, validator: PrefixFrictionValidator
    ) -> None:
        # No env flag present → nothing to normalize; let native matching
        # handle the already-covered `uv run pytest` form.
        assert validator.should_run(inp=_make_input(command="uv run pytest tests/")) is False

    def test_no_allow_patterns_no_opinion(self) -> None:
        v = PrefixFrictionValidator()
        v._allow_patterns = []
        result = v.validate(inp=_make_input(command="uv run --directory apps/api pytest"))
        assert result is None

    def test_lazy_loads_allow_patterns_when_unset(self) -> None:
        from unittest.mock import patch

        from dev10x.domain import HookAllow

        v = PrefixFrictionValidator()  # _allow_patterns starts None
        with patch(
            "dev10x.validators.prefix_friction._load_all_allow_patterns",
            return_value=["uv run pytest"],
        ):
            result = v.validate(inp=_make_input(command="uv run --directory apps/api pytest"))
        assert isinstance(result, HookAllow)

    def test_correct_returns_none_for_uv_run_allow(
        self, validator: PrefixFrictionValidator
    ) -> None:
        # A HookAllow from validate() must not be turned into a retry.
        result = validator.correct(inp=_make_input(command="uv run --directory apps/api pytest"))
        assert result is None

    def test_correct_returns_retry_for_friction_command(
        self, validator: PrefixFrictionValidator
    ) -> None:
        from dev10x.domain import HookRetry

        result = validator.correct(
            inp=_make_input(command="mkdir -p /tmp/foo && ~/.claude/tools/x.sh")
        )
        assert isinstance(result, HookRetry)

    def test_correct_returns_none_when_no_friction(
        self, validator: PrefixFrictionValidator
    ) -> None:
        result = validator.correct(inp=_make_input(command="uv run --directory apps/api rm -rf x"))
        assert result is None
