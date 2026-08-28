from __future__ import annotations

import pytest

from dev10x.domain.common.bash_tokens import (
    ANY_CASE_ENV_VAR_RE,
    ENV_VAR_RE,
    GIT_C_DIR_RE,
    GIT_C_PREFIX_RE,
    split_tokens,
)


class TestEnvVarRe:
    @pytest.mark.parametrize("token", ["FOO=bar", "_X=1", "A1_B=", "PATH=/usr/bin"])
    def test_matches_env_assignments(self, token: str) -> None:
        assert ENV_VAR_RE.match(token)

    @pytest.mark.parametrize("token", ["foo=bar", "1FOO=x", "FOO", "FOO=a b", "git"])
    def test_rejects_non_env_tokens(self, token: str) -> None:
        assert ENV_VAR_RE.match(token) is None


class TestAnyCaseEnvVarRe:
    """GH-1084: the executable-resolution variant also accepts lowercase."""

    @pytest.mark.parametrize(
        "token",
        ["FOO=bar", "_X=1", "A1_B=", "PATH=/usr/bin", "foo=bar", "mixedCase=1"],
    )
    def test_matches_env_assignments_in_any_case(self, token: str) -> None:
        assert ANY_CASE_ENV_VAR_RE.match(token)

    @pytest.mark.parametrize("token", ["1FOO=x", "FOO", "FOO=a b", "git", "./script.sh"])
    def test_rejects_non_env_tokens(self, token: str) -> None:
        assert ANY_CASE_ENV_VAR_RE.match(token) is None

    def test_lowercase_is_the_only_difference_from_env_var_re(self) -> None:
        """Keeps the two regexes from drifting apart on anything else."""
        assert ANY_CASE_ENV_VAR_RE.pattern == ENV_VAR_RE.pattern.replace("A-Z", "A-Za-z")


class TestSplitTokens:
    def test_splits_respecting_quotes(self) -> None:
        assert split_tokens(command="cmd 'a b' c") == ["cmd", "a b", "c"]

    def test_falls_back_to_whitespace_on_unbalanced_quote(self) -> None:
        """Refusing to tokenize would hand a caller an evasion, not safety."""
        assert split_tokens(command='git -C "unclosed push') == ["git", "-C", '"unclosed', "push"]


class TestGitCPrefixRe:
    @pytest.mark.parametrize("command", ["git -C /repo status", "git   -C   /repo log"])
    def test_matches_leading_git_c(self, command: str) -> None:
        assert GIT_C_PREFIX_RE.match(command)

    @pytest.mark.parametrize(
        "command",
        ["git status", "git -c core.pager=cat log", " git -C /repo status"],
    )
    def test_rejects_non_prefix(self, command: str) -> None:
        assert GIT_C_PREFIX_RE.match(command) is None


class TestGitCDirRe:
    def test_captures_bare_directory(self) -> None:
        match = GIT_C_DIR_RE.search("git -C /work/repo status")
        assert match is not None
        assert match.group(1) == "/work/repo"

    def test_captures_quoted_directory(self) -> None:
        match = GIT_C_DIR_RE.search('git -C "/with space" log')
        assert match is not None
        assert match.group(1) == '"/with space"'

    def test_matches_mid_command(self) -> None:
        # Distinct from GIT_C_PREFIX_RE: this one searches anywhere.
        match = GIT_C_DIR_RE.search("cd /tmp && git -C /repo status")
        assert match is not None
        assert match.group(1) == "/repo"

    def test_lowercase_config_flag_is_not_a_dir(self) -> None:
        assert GIT_C_DIR_RE.search("git -c core.pager=cat log") is None
