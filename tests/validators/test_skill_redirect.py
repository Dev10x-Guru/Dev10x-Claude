"""Tests for SkillRedirectValidator."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from dev10x.validators.skill_redirect import (
    _YAML_PATH,
    SkillRedirectValidator,
    _load_config,
)
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(
        tool_name="Bash",
        command=command,
        raw={"tool_name": "Bash", "tool_input": {"command": command}},
    )


@pytest.fixture()
def validator() -> SkillRedirectValidator:
    return SkillRedirectValidator()


class TestShouldRun:
    def test_true_for_git_commit(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command='git commit -m "some message"')
        assert validator.should_run(inp=inp) is True

    def test_true_for_gh_pr_create(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr create --title 'test'")
        assert validator.should_run(inp=inp) is True

    def test_true_for_git_push(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin main")
        assert validator.should_run(inp=inp) is True

    def test_true_for_git_rebase(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git rebase -i HEAD~3")
        assert validator.should_run(inp=inp) is True

    def test_true_for_gh_pr_checks(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr checks --watch")
        assert validator.should_run(inp=inp) is True

    def test_false_for_unrelated_command(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git status")
        assert validator.should_run(inp=inp) is False

    def test_false_for_git_log(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git log --oneline -5")
        assert validator.should_run(inp=inp) is False


class TestPsqlWriteRedirect:
    """GH-1034: destructive psql must reach evaluate_command() and block."""

    @pytest.mark.parametrize(
        "verb",
        ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "GRANT", "REVOKE"],
    )
    def test_should_run_for_psql_write(self, validator: SkillRedirectValidator, verb: str) -> None:
        """Without a quick token for the client, should_run() short-circuits
        before the rule is ever evaluated."""
        inp = _make_input(command=f"docker exec c psql -d db -c '{verb} FROM users'")
        assert validator.should_run(inp=inp) is True

    @pytest.mark.parametrize(
        "command",
        [
            "docker exec tt-pos-postgis psql -U u -d postgres -c 'DROP DATABASE IF EXISTS t'",
            "psql -d postgres -c 'TRUNCATE users'",
            "psql -d mydb -f /tmp/teardown.sql",
            "psql -d postgres -tAc 'DROP TABLE users'",
            "psql -d mydb -tAf /tmp/teardown.sql",
        ],
    )
    def test_blocks_psql_write(self, validator: SkillRedirectValidator, command: str) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:db-psql" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            "docker exec c psql -d db -c 'SELECT count(*) FROM users'",
            "psql -d mydb -c 'SELECT 1'",
        ],
    )
    def test_reads_stay_advisory(self, validator: SkillRedirectValidator, command: str) -> None:
        """The generic psql rule is hook_block: false — reads must not hard-block."""
        inp = _make_input(command=command)
        assert validator.validate(inp=inp) is None


class TestGitCommitRedirect:
    def test_blocks_git_commit_with_m_flag(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command='git commit -m "Enable feature X"')
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git-commit" in result.message

    def test_blocks_git_commit_with_m_single_quotes(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git commit -m 'Enable feature X'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git-commit" in result.message

    def test_allows_git_commit_f_with_skill_temp(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git commit -F /tmp/Dev10x/git/commit-msg.W9DryMXsQ5Aw.txt")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_git_commit_f_with_alternate_prefix(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git commit -F /tmp/Dev10x/git/msg.RnUr0daBNpSj.txt")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_git_commit_f_without_mktmp_suffix(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git commit -F /tmp/Dev10x/git/commit-259-v2.txt")
        result = validator.validate(inp=inp)
        assert result is None

    def test_blocks_git_commit_f_with_arbitrary_path(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git commit -F /tmp/random/msg.txt")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git-commit" in result.message

    def test_blocks_git_commit_f_with_non_git_namespace(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git commit -F /tmp/Dev10x/commit/msg.knDXJdfzYnVI.txt")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__mktmp" in result.message
        assert "wrong temp file path" in result.message

    def test_healing_msg_suggests_git_namespace(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git commit -F /tmp/Dev10x/commit/msg.abc123.txt")
        result = validator.validate(inp=inp)
        assert result is not None
        assert 'namespace="git"' in result.message

    def test_blocks_git_commit_without_flags(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git commit")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git-commit" in result.message

    def test_allows_git_commit_fixup(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git commit --fixup=abc1234")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_git_commit_amend(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git commit --amend")
        result = validator.validate(inp=inp)
        assert result is None


class TestGhPrCreateRedirect:
    def test_blocks_gh_pr_create(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr create --title 'Fix bug' --body 'details'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:gh-pr-create" in result.message

    def test_blocks_gh_pr_create_minimal(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr create")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:gh-pr-create" in result.message


class TestGitPushRedirect:
    def test_blocks_git_push_to_protected_branch(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git" in result.message

    def test_allows_git_push_force_with_lease(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push --force-with-lease")
        result = validator.validate(inp=inp)
        assert result is None

    def test_blocks_git_push_u_to_protected_branch(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git push -u origin develop")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git" in result.message


class TestGitPushUnattendedEscapeHatch:
    """GH-963: a non-force push naming an explicit, non-protected branch
    needs neither the skill nor MCP — it is already the safe case
    push_safe/git-push-safe.sh would have allowed anyway."""

    def test_allows_push_to_explicit_feature_branch(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git push origin feature-branch")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_push_u_to_explicit_feature_branch(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git push -u origin janusz/GH-963/my-fix")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_refspec_form(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin my-branch:my-branch")
        result = validator.validate(inp=inp)
        assert result is None

    def test_blocks_bare_push_no_resolvable_target(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git push")
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_push_with_remote_only(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin")
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_push_symbolic_head_ref(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin HEAD")
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_bare_force_to_feature_branch(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push --force origin feature-branch")
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_short_force_flag_to_feature_branch(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="git push -f origin feature-branch")
        result = validator.validate(inp=inp)
        assert result is not None

    @pytest.mark.parametrize(
        "command",
        [
            "git push -uf origin feature-branch",
            "git push -fu origin feature-branch",
            "git push -vuf origin feature-branch",
        ],
    )
    def test_blocks_bundled_short_force_flag(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        """GH-1047: POSIX short flags bundle, so a force push can be
        spelled without ever producing a lone ``-f`` token."""
        result = validator.validate(inp=_make_input(command=command))
        assert result is not None

    @pytest.mark.parametrize(
        "command",
        [
            "git push -u origin feature-branch",
            "git push -vu origin feature-branch",
            "git push --force-with-lease origin feature-branch",
        ],
    )
    def test_allows_non_force_flags_without_f(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        """GH-1047: cluster decomposition must not report a force push
        for clusters that carry no ``f``, nor match ``--force-with-lease``
        on a substring."""
        result = validator.validate(inp=_make_input(command=command))
        assert result is None

    def test_still_blocks_protected_branch_by_name(
        self, validator: SkillRedirectValidator
    ) -> None:
        for branch in ("main", "develop", "master", "development", "trunk"):
            inp = _make_input(command=f"git push origin {branch}")
            result = validator.validate(inp=inp)
            assert result is not None, f"Expected block for push to {branch}"


class TestGitPushForceSpellingsThatEvadedTheGuard:
    """GH-1049: six spellings that read as a safe push but force-push a
    protected branch.

    GH-1047 closed the bundled-short-flag hole; these are the remaining
    ones, all sharing a root cause — the guard decides "is this a force
    push, and what does it target?" by statically matching the command
    text, and each case below is a spelling that static matching missed.

    Every case must produce a block, i.e. route to ``Skill(Dev10x:git)``
    rather than being waved through as the safe direct-push case.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "git push -o ci.skip origin main",
            "git push --push-option ci.skip origin develop",
            "git push --receive-pack /usr/bin/git-receive-pack origin master",
        ],
    )
    def test_value_taking_flag_value_is_not_read_as_a_positional(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        """Gap 2: dropping only ``-``-prefixed tokens leaves the flag's
        value in the positional list, shifting every index after it — so
        the remote was read as the branch and the real branch never
        reached the protected-branch check."""
        assert validator.validate(inp=_make_input(command=command)) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "git push origin +evil:main",
            "git push origin +main",
            "git push origin feature +evil:develop",
        ],
    )
    def test_plus_prefixed_refspec_counts_as_force(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        """Gap 3: refspec syntax force-pushes with no force *flag* at all,
        and only the first refspec was ever inspected."""
        assert validator.validate(inp=_make_input(command=command)) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "git push origin +feature:refs/heads/main",
            "git push --force origin refs/heads/develop",
        ],
    )
    def test_fully_qualified_ref_is_recognised_as_protected(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        """Gap 4: ``PROTECTED_BRANCHES`` holds short names, so a
        ``refs/heads/``-qualified target compared as unprotected."""
        assert validator.validate(inp=_make_input(command=command)) is not None

    def test_decoy_push_token_cannot_shift_target_resolution(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        """Gap 5: the subcommand was located by the first bare ``push``
        anywhere in the string, so an earlier decoy shifted every offset."""
        command = "echo push && git push origin +evil:main"
        assert validator.validate(inp=_make_input(command=command)) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "git push origin $BRANCH",
            "git push origin ${TARGET}",
            "git push $(cat /tmp/flags) origin feature",
            "git push origin feature-`date +%s`",
        ],
    )
    def test_shell_expansion_fails_closed(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        """Gap 6: an expansion can produce a force flag or a protected
        target at execution time with no matching token in the parsed
        text. What the guard cannot read, it must not clear."""
        assert validator.validate(inp=_make_input(command=command)) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "git push -o ci.skip origin feature-branch",
            "git push origin feature:refs/heads/feature",
            "git push origin feature other-feature",
        ],
    )
    def test_ordinary_safe_pushes_still_pass(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        """The escape hatch must survive the tightening: these name
        explicit, non-protected targets and carry no force in any
        spelling."""
        assert validator.validate(inp=_make_input(command=command)) is None


class TestPushHelpersOnNonPushCommands:
    """GH-1049: the helpers must answer safely for a command with no
    ``git push`` in it at all.

    The validator only reaches them behind the ``git-push`` rule, so these
    branches are unreachable through ``validate``. They are still the
    contract every helper leans on — ``_has_refspec_force`` must not report
    force, and target resolution must not invent a target, when there is no
    push to read. Exercised directly rather than left to a future caller to
    discover.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "echo push",
            "git status",
            "npm run push",
            "",
        ],
    )
    def test_no_git_push_yields_no_args(self, command: str) -> None:
        from dev10x.validators.skill_redirect import _push_args

        assert _push_args(command) is None

    @pytest.mark.parametrize("command", ["echo push", "git status"])
    def test_no_git_push_yields_no_targets(self, command: str) -> None:
        from dev10x.validators.skill_redirect import _explicit_push_targets

        assert _explicit_push_targets(command) is None

    @pytest.mark.parametrize("command", ["echo push +evil:main", "git status"])
    def test_no_git_push_is_not_refspec_force(self, command: str) -> None:
        from dev10x.validators.skill_redirect import _has_refspec_force

        assert _has_refspec_force(command) is False

    def test_unbalanced_quotes_fall_back_to_whitespace_split(self) -> None:
        """``shlex`` raises on an unterminated quote; the fallback keeps the
        guard reading the command instead of throwing inside a hook."""
        from dev10x.validators.skill_redirect import _tokenize

        assert _tokenize("git push origin 'unterminated") == [
            "git",
            "push",
            "origin",
            "'unterminated",
        ]


class TestGitRebaseRedirect:
    def test_blocks_git_rebase_i(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git rebase -i HEAD~3")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git-groom" in result.message

    def test_blocks_git_rebase_interactive(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git rebase --interactive HEAD~5")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:git-groom" in result.message

    def test_allows_git_rebase_continue(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git rebase --continue")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_git_rebase_onto(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git rebase origin/develop")
        result = validator.validate(inp=inp)
        assert result is None


class TestGhPrChecksWatchRedirect:
    def test_blocks_gh_pr_checks_watch(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr checks --watch")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:gh-pr-monitor" in result.message

    def test_blocks_gh_pr_checks_w(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr checks -w")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:gh-pr-monitor" in result.message

    def test_allows_gh_pr_checks_without_watch(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr checks")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_gh_pr_checks_with_pr_number(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr checks 42")
        result = validator.validate(inp=inp)
        assert result is None


class TestGhPrMergeRedirect:
    def test_blocks_gh_pr_merge(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr merge 111 --squash --delete-branch")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:gh-pr-merge" in result.message

    def test_blocks_gh_pr_merge_minimal(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr merge")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:gh-pr-merge" in result.message

    def test_blocks_gh_pr_merge_rebase(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr merge 42 --rebase")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Dev10x:gh-pr-merge" in result.message

    def test_should_run_true_for_gh_pr_merge(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr merge 111 --squash")
        assert validator.should_run(inp=inp) is True

    def test_message_includes_pre_merge_checks(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr merge 111 --squash")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "pre-merge checks" in result.message


class TestGhPrViewRedirect:
    """gh pr view routes to pr_get unless it carries the DoD allow marker (GH-668)."""

    def test_blocks_gh_pr_view_isdraft(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr view 42 --json isDraft")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__pr_get" in result.message

    def test_blocks_gh_pr_view_minimal(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr view 7")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__pr_get" in result.message

    def test_allows_gh_pr_view_with_cli_friction_marker(
        self, validator: SkillRedirectValidator
    ) -> None:
        """DoD-runner check templates carry the marker and must NOT be blocked."""
        inp = _make_input(
            command=(
                "gh pr view 42 --repo o/r --json isDraft -q .isDraft  "
                "# cli-friction: allow raw-gh-pr — DoD runner executes this template"
            )
        )
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_gh_pr_view_review_requests_with_marker(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(
            command=(
                "gh pr view 42 --repo o/r --json reviewRequests "
                "-q '.reviewRequests | length'  # cli-friction: allow raw-gh-pr"
            )
        )
        result = validator.validate(inp=inp)
        assert result is None


class TestGhIssueViewRedirect:
    def test_blocks_gh_issue_view(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue view 539 --repo Dev10x-Guru/dev10x-claude")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_get" in result.message

    def test_blocks_gh_issue_view_with_json(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue view 42 --json title,body,state")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_get" in result.message

    def test_blocks_gh_issue_view_minimal(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue view 10")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_get" in result.message

    def test_mcp_message_uses_tool_label(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue view 1")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "MCP tool" in result.message
        assert "Skill(" not in result.message

    def test_should_run_true_for_gh_issue_view(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue view 539")
        assert validator.should_run(inp=inp) is True


class TestGhIssueCreateRedirect:
    def test_blocks_gh_issue_create(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue create --title 'Fix bug' --body 'Details'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_create" in result.message

    def test_blocks_gh_issue_create_minimal(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue create --title 'New feature'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_create" in result.message

    def test_mcp_message_uses_tool_label(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue create --title test")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "MCP tool" in result.message
        assert "Skill(" not in result.message

    def test_should_run_true_for_gh_issue_create(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue create --title test")
        assert validator.should_run(inp=inp) is True


class TestSearchToolFalsePositive:
    """GH-210: filename appearing as a search argument is not a script call."""

    def test_find_name_git_push_safe_allowed(self, validator: SkillRedirectValidator) -> None:
        cmd = "find . -path ./node_modules -prune -o -name 'git-push-safe.sh' -print"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is None

    def test_grep_l_git_push_safe_allowed(self, validator: SkillRedirectValidator) -> None:
        cmd = "grep -l git-push-safe.sh src/"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is None

    def test_rg_git_push_safe_allowed(self, validator: SkillRedirectValidator) -> None:
        result = validator.validate(inp=_make_input(command="rg git-push-safe.sh src/"))
        assert result is None

    def test_xargs_with_filename_allowed(self, validator: SkillRedirectValidator) -> None:
        cmd = "xargs grep git-rebase-groom.sh"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is None

    def test_bash_wrapped_find_allowed(self, validator: SkillRedirectValidator) -> None:
        cmd = "bash -c 'find . -name git-push-safe.sh'"
        result = validator.validate(inp=_make_input(command=cmd))
        # GH-1084 made this assertable: the script name sits inside the
        # `-c` payload, never in an invocation position, so the rule no
        # longer fires. Previously the tokenizer could not see past the
        # wrapper and the test asserted a tautology.
        assert result is None

    def test_direct_script_invocation_still_blocked(
        self, validator: SkillRedirectValidator
    ) -> None:
        cmd = "/work/skills/git/scripts/git-push-safe.sh origin develop"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__push_safe" in result.message

    def test_bash_invocation_still_blocked(self, validator: SkillRedirectValidator) -> None:
        cmd = "bash git-push-safe.sh origin develop"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__push_safe" in result.message

    def test_find_with_exec_still_blocks(self, validator: SkillRedirectValidator) -> None:
        cmd = "find . -name '*.sh' -exec git-push-safe.sh {} ;"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is not None


class TestScriptMentionVsInvocation:
    """GH-1084: `match_position: invocation` guards running a guarded
    script, not naming it.

    The rule's pattern is a bare filename, and patterns are searched
    against the whole command string, so every command that merely
    CONTAINED `git-push-safe.sh` was denied — including the two the
    supervisor hit while shipping the force-push guard itself: linting
    the script through pre-commit, and renaming it. Neither executes
    anything, and `push_safe` — the compensation the block names — can
    neither lint nor move a file, so the steer had no valid target."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "pre-commit run --files skills/git/scripts/git-push-safe.sh",
            "pre-commit run --all-files --files skills/git/scripts/git-push-safe.sh",
            "mv /tmp/Dev10x/git-push-safe.sh /tmp/Dev10x/oldguard.sh",
            "cp skills/git/scripts/git-push-safe.sh /tmp/Dev10x/backup.sh",
            "shellcheck skills/git/scripts/git-push-safe.sh",
            "wc -l skills/git/scripts/git-push-safe.sh",
        ],
    )
    def test_mentioning_the_script_is_allowed(
        self,
        cmd: str,
        validator: SkillRedirectValidator,
    ) -> None:
        assert validator.validate(inp=_make_input(command=cmd)) is None

    @pytest.mark.parametrize(
        "cmd",
        [
            "skills/git/scripts/git-push-safe.sh --force origin main",
            "./git-push-safe.sh --force origin main",
            "/work/skills/git/scripts/git-push-safe.sh origin develop",
            "bash skills/git/scripts/git-push-safe.sh --force origin main",
        ],
    )
    def test_running_the_script_is_still_denied(
        self,
        cmd: str,
        validator: SkillRedirectValidator,
    ) -> None:
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__push_safe" in result.message

    @pytest.mark.parametrize(
        "cmd",
        [
            "GIT_TRACE=1 skills/git/scripts/git-push-safe.sh --force origin main",
            "FOO=bar BAZ=qux ./git-push-safe.sh --force origin main",
            "env GIT_TRACE=1 skills/git/scripts/git-push-safe.sh --force origin main",
        ],
    )
    def test_env_assignment_prefix_does_not_evade_the_deny(
        self,
        cmd: str,
        validator: SkillRedirectValidator,
    ) -> None:
        """An assignment prefix changes the environment, not the program."""
        assert validator.validate(inp=_make_input(command=cmd)) is not None

    def test_script_after_a_chain_operator_is_still_denied(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        """Each shell segment carries its own invocation position."""
        cmd = "echo starting && skills/git/scripts/git-push-safe.sh --force origin main"
        assert validator.validate(inp=_make_input(command=cmd)) is not None


class TestGhPrEditRedirect:
    def test_blocks_gh_pr_edit(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr edit 203 --title '♻️ GH-90 Bundle'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__update_pr" in result.message

    def test_blocks_gh_pr_edit_body(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr edit 42 --body-file /tmp/body.md")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__update_pr" in result.message

    def test_blocks_gh_pr_edit_label(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr edit 1 --add-label bug")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__update_pr" in result.message

    def test_mcp_message_uses_tool_label(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr edit 1 --title hi")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "MCP tool" in result.message
        assert "Skill(" not in result.message

    def test_should_run_true_for_gh_pr_edit(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh pr edit 1 --title hi")
        assert validator.should_run(inp=inp) is True


class TestGhIssueEditRedirect:
    def test_blocks_gh_issue_edit(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue edit 42 --title 'New title'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_edit" in result.message

    def test_blocks_gh_issue_edit_milestone(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue edit 1 --milestone 'M2'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_edit" in result.message

    def test_should_run_true_for_gh_issue_edit(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue edit 1 --title hi")
        assert validator.should_run(inp=inp) is True


class TestGhIssueCommentRedirect:
    def test_blocks_gh_issue_comment(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue comment 42 --body 'thanks'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_comment" in result.message

    def test_blocks_gh_issue_comment_body_file(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue comment 1 --body-file /tmp/c.md")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__issue_comment" in result.message


class TestGhMilestoneCreateRedirect:
    def test_blocks_milestone_create_method_post(self, validator: SkillRedirectValidator) -> None:
        cmd = "gh api repos/Dev10x-Guru/Dev10x-Claude/milestones --method POST -f title=M3"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__milestone_create" in result.message

    def test_blocks_milestone_create_x_post(self, validator: SkillRedirectValidator) -> None:
        cmd = "gh api repos/o/r/milestones -X POST -f title=M"
        result = validator.validate(inp=_make_input(command=cmd))
        assert result is not None
        assert "mcp__plugin_Dev10x_cli__milestone_create" in result.message


class TestMessageContent:
    def test_message_includes_skill_name(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Skill(Dev10x:git)" in result.message

    def test_message_includes_guardrails(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "protected branch" in result.message

    def test_message_includes_blocked_indicator(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "blocked" in result.message

    def test_message_includes_file_issue_hint(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "file an issue" in result.message
        assert "Dev10x-Guru/dev10x-claude" in result.message


class TestBlockMessageFallback:
    """GH-1194: the fallback clause is unconditional.

    It used to vary by the ADR-0002 `config.friction_level` axis, which
    only ever shipped as `guided`. With the axis collapsed, an agent that
    cannot reach the sanctioned path always sees what to do instead —
    which is the behaviour every real session already got.
    """

    def _make_yaml(
        self,
        *,
        fallback: str = "",
        description: str = "",
        comp_type: str = "use-skill",
    ) -> str:
        # The two branches read different fields: `use-skill` renders
        # `fallback`, `use-tool` renders `description` as its
        # MCP-unavailable escape.
        skill_or_tool = "skill" if comp_type == "use-skill" else "tool"
        return textwrap.dedent(
            f"""\
            config:
              plugin_repo: https://github.com/Dev10x-Guru/dev10x-claude
            rules:
              - name: test-rule
                matcher: Bash
                patterns:
                  - test cmd
                except: []
                hook_block: true
                compensations:
                  - type: {comp_type}
                    {skill_or_tool}: Dev10x:test-skill
                    guardrails: test guardrail
                    description: "{description}"
                    fallback: "{fallback}"
        """
        )

    def _validate(self, *, yaml_file: Path):
        config, engine = _load_config(yaml_path=yaml_file)
        validator = SkillRedirectValidator()
        inp = _make_input(command="test cmd foo")

        import dev10x.validators.skill_redirect as mod

        orig_config, orig_engine = mod._CONFIG, mod._ENGINE
        mod._CONFIG, mod._ENGINE = config, engine
        try:
            return config, validator.validate(inp=inp)
        finally:
            mod._CONFIG, mod._ENGINE = orig_config, orig_engine

    def test_skill_fallback_is_always_included(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "map.yaml"
        yaml_file.write_text(self._make_yaml(fallback="Apply manual guardrail here."))

        _config, result = self._validate(yaml_file=yaml_file)

        assert result is not None
        assert "Apply manual guardrail here." in result.message

    def test_absent_fallback_adds_no_empty_clause(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "map.yaml"
        yaml_file.write_text(self._make_yaml(fallback=""))

        _config, result = self._validate(yaml_file=yaml_file)

        assert result is not None
        assert "apply these guardrails manually" not in result.message

    def test_config_carries_no_friction_level(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "map.yaml"
        yaml_file.write_text(self._make_yaml(fallback="x"))

        config, _result = self._validate(yaml_file=yaml_file)

        assert not hasattr(config, "friction_level")

    def test_hook_block_false_entries_not_loaded(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "map.yaml"
        yaml_file.write_text(
            textwrap.dedent(
                """\
                config:
                  plugin_repo: https://github.com/Dev10x-Guru/dev10x-claude
                rules:
                  - name: ignored-rule
                    matcher: Bash
                    patterns:
                      - ignored cmd
                    hook_block: false
                    compensations:
                      - type: use-skill
                        skill: Dev10x:ignored
            """
            )
        )
        config, _engine = _load_config(yaml_path=yaml_file)
        assert config.rules == []

    def test_mcp_type_uses_mcp_template_with_fallback(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "map.yaml"
        yaml_file.write_text(
            self._make_yaml(
                description="Use gh issue view directly.",
                comp_type="use-tool",
            )
        )

        _config, result = self._validate(yaml_file=yaml_file)

        assert result is not None
        assert "MCP tool" in result.message
        assert "Skill(" not in result.message
        assert "Use gh issue view directly." in result.message

    def test_mcp_type_without_fallback_still_uses_mcp_template(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "map.yaml"
        yaml_file.write_text(self._make_yaml(comp_type="use-tool"))

        _config, result = self._validate(yaml_file=yaml_file)

        assert result is not None
        assert "MCP tool" in result.message
        assert "Skill(" not in result.message


_RULES: list[dict] = yaml.safe_load(_YAML_PATH.read_text())["rules"]
_HOOK_BLOCK_RULES: list[dict] = [entry for entry in _RULES if entry.get("hook_block")]
_COMPENSATION_PAIRS: list[tuple[str, str]] = [
    (entry.get("name", "<unnamed>"), comp["type"])
    for entry in _RULES
    for comp in entry.get("compensations", [])
]


def _rule_ids(rules: list[dict]) -> list[str]:
    return [entry.get("name", f"rule-{i}") for i, entry in enumerate(rules)]


class TestYamlSchema:
    def test_yaml_file_is_valid(self) -> None:
        data = yaml.safe_load(_YAML_PATH.read_text())
        assert "config" in data
        assert "rules" in data
        assert data["config"]["plugin_repo"]
        # GH-1194: the ADR-0002 command-redirect axis is collapsed. A
        # re-added key would be inert — nothing reads it — so assert its
        # absence rather than letting it drift back in as decoration.
        assert "friction_level" not in data["config"]

    @pytest.mark.parametrize("entry", _HOOK_BLOCK_RULES, ids=_rule_ids(_HOOK_BLOCK_RULES))
    def test_hook_block_entry_has_compensations(self, entry: dict) -> None:
        assert "compensations" in entry, f"{entry['name']} missing compensations"
        assert entry["compensations"], f"{entry['name']} has empty compensations"

    @pytest.mark.parametrize("entry", _RULES, ids=_rule_ids(_RULES))
    def test_rule_has_name(self, entry: dict) -> None:
        assert "name" in entry, f"Rule missing name: {entry}"
        assert entry["name"], f"Rule has empty name: {entry}"

    @pytest.mark.parametrize("entry", _RULES, ids=_rule_ids(_RULES))
    def test_rule_has_matcher(self, entry: dict) -> None:
        assert "matcher" in entry, f"{entry['name']} missing matcher"
        assert entry["matcher"] in {
            "Bash",
            "Edit|Write",
        }, f"{entry['name']} has invalid matcher: {entry['matcher']}"

    @pytest.mark.parametrize(
        ("rule_name", "comp_type"),
        _COMPENSATION_PAIRS,
        ids=[f"{name}:{ctype}" for name, ctype in _COMPENSATION_PAIRS],
    )
    def test_compensation_type_is_valid(self, rule_name: str, comp_type: str) -> None:
        valid_types = {
            "use-skill",
            "use-tool",
            "use-alternative",
            "split-commands",
            "change-cwd",
            "use-alias",
            "use-file-flag",
            "file-issue",
        }
        assert comp_type in valid_types, f"{rule_name} has invalid compensation type: {comp_type}"


class TestLegitimateSkillCommands:
    """Commands that skills legitimately instruct — must NOT be blocked."""

    @pytest.mark.parametrize(
        ("command", "description"),
        [
            ("git commit --fixup=abc1234", "git-fixup skill creates fixup commits"),
            ("git commit --amend", "git-groom may amend during rebase"),
            (
                "git commit -F /tmp/Dev10x/git/commit-msg.abc123.txt",
                "git-commit skill uses -F with mktmp path",
            ),
            (
                "git push --force-with-lease origin feature-branch",
                "git-groom pushes with --force-with-lease",
            ),
            (
                "git push --force-with-lease",
                "git skill pushes with --force-with-lease",
            ),
            (
                'gh issue create --repo owner/repo --title "Fix bug" --body-file /tmp/body.md',
                "ticket-create uses --body-file for issue creation",
            ),
            ("git rebase --continue", "git-groom continues interrupted rebase"),
            ("git rebase origin/develop", "git-groom rebases onto base branch"),
            ("gh pr checks 42", "gh-pr-monitor checks status without --watch"),
            ("gh pr checks", "checking PR status without --watch flag"),
        ],
    )
    def test_allows_legitimate_skill_command(
        self,
        validator: SkillRedirectValidator,
        command: str,
        description: str,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None, (
            f"Blocked legitimate command: {command}\n"
            f"Context: {description}\n"
            f"Message: {result.message if result else 'N/A'}"
        )


class TestCommandPrefixOverride:
    """DEV10X_SKIP_CMD_VALIDATION rationale form bypasses, boolean is rejected (GH-226)."""

    def test_rationale_form_bypasses_should_run(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        inp = _make_input(
            command=(
                'DEV10X_SKIP_CMD_VALIDATION="inside Dev10x:git-commit skill: '
                'commit -F path validated by mktmp" git commit -F /tmp/x.txt'
            )
        )
        assert validator.should_run(inp=inp) is False

    @pytest.mark.parametrize(
        "command",
        [
            "DEV10X_SKIP_CMD_VALIDATION=true git push origin main",
            "DEV10X_SKIP_CMD_VALIDATION=True git commit -m 'test'",
            "DEV10X_SKIP_CMD_VALIDATION=1 gh pr create --title test",
            "DEV10X_SKIP_CMD_VALIDATION=yes gh issue view 42",
        ],
    )
    def test_boolean_form_is_rejected(
        self,
        validator: SkillRedirectValidator,
        command: str,
    ) -> None:
        inp = _make_input(command=command)
        assert validator.should_run(inp=inp) is True
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Un-rationalized" in result.message
        assert "rationale string of at least 20 chars" in result.message

    def test_short_rationale_is_rejected(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        """Rationale strings shorter than 20 chars don't qualify as bypass."""
        inp = _make_input(command='DEV10X_SKIP_CMD_VALIDATION="too short" git push origin main')
        assert validator.should_run(inp=inp) is True

    def test_no_prefix_does_not_bypass(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        inp = _make_input(command="git push origin main")
        assert validator.should_run(inp=inp) is True

    def test_override_hint_shows_rationale_form(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert 'DEV10X_SKIP_CMD_VALIDATION="' in result.message
        assert "rationale" in result.message.lower()

    def test_override_hint_calls_out_boolean_rejection(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "boolean form" in result.message.lower()
        assert "GH-226" in result.message

    def test_hint_instructs_prefix_not_env_var(
        self,
        validator: SkillRedirectValidator,
    ) -> None:
        inp = _make_input(command="git push origin main")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "prefix it with" in result.message


class TestMcpUnavailableHint:
    """MCP tool redirect messages must warn against DEV10X_SKIP_CMD_VALIDATION
    as a workaround for MCP disconnect (GH-957)."""

    def test_mcp_block_includes_reconnect_guidance(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command="gh issue view 42")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "MCP server is disconnected" in result.message
        assert "/mcp" in result.message

    def test_mcp_block_warns_against_skip_flag(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="gh issue view 42")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Do NOT use DEV10X_SKIP_CMD_VALIDATION" in result.message

    def test_skill_redirect_does_not_include_mcp_hint(
        self, validator: SkillRedirectValidator
    ) -> None:
        inp = _make_input(command='git commit -m "test"')
        result = validator.validate(inp=inp)
        assert result is not None
        assert "MCP server is disconnected" not in result.message


class TestBlockedVsAllowed:
    """Verify the boundary between blocked and allowed for each hook rule."""

    @pytest.mark.parametrize(
        ("command", "should_block"),
        [
            ("git push origin main", True),
            ("git push -u origin feature", False),
            ("git push --force-with-lease origin feature", False),
            ("git push --force-with-lease", False),
            ("git push --force origin feature", True),
            ("git push -f origin feature", True),
            ("git push -uf origin feature", True),
            ("git push", True),
            ("git push origin", True),
            ("git push origin HEAD", True),
            ("git commit -m 'test'", True),
            ("git commit --fixup=abc", False),
            ("git commit --amend", False),
            ("git commit -F /tmp/Dev10x/git/msg.abc.txt", False),
            ("gh pr create --title test", True),
            ("gh issue view 42", True),
            ("gh issue create --title test", True),
            ("gh issue create --body-file /tmp/body.md --title test", False),
            ("git rebase -i HEAD~3", True),
            ("git rebase --interactive develop", True),
            ("git rebase --continue", False),
            ("git rebase origin/develop", False),
            ("gh pr checks --watch", True),
            ("gh pr checks -w", True),
            ("gh pr checks 42", False),
            ("gh pr checks", False),
            ("gh pr merge 111 --squash --delete-branch", True),
            ("gh pr merge", True),
            ("gh pr merge 42 --rebase", True),
        ],
    )
    def test_blocked_vs_allowed(
        self,
        validator: SkillRedirectValidator,
        command: str,
        should_block: bool,
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        if should_block:
            assert result is not None, f"Expected block for: {command}"
        else:
            assert result is None, (
                f"Unexpected block for: {command}\nMessage: {result.message if result else 'N/A'}"
            )


class TestNodeTestsNpmMonorepo:
    """GH-880: scoped monorepo `npm --prefix <dir> test` is hard-blocked and
    steered to run_node_tests; plain `npm test` / `npm run test` are not."""

    def test_should_run_true_for_npm(self, validator: SkillRedirectValidator) -> None:
        inp = _make_input(command="npm --prefix apps/web test -- NavList")
        assert validator.should_run(inp=inp) is True

    @pytest.mark.parametrize(
        "command",
        [
            "npm --prefix apps/web test -- NavList",
            "npm --prefix=apps/web test",
            "npm -C apps/web test",
            "npm -w web test",
            "npm --prefix apps/web test -- NavList 2>&1 | tail -30",
        ],
    )
    def test_blocks_monorepo_scoped_test(
        self, validator: SkillRedirectValidator, command: str
    ) -> None:
        result = validator.validate(inp=_make_input(command=command))
        assert result is not None
        assert "run_node_tests" in result.message

    def test_block_message_carries_cwd_translation(
        self, validator: SkillRedirectValidator
    ) -> None:
        result = validator.validate(
            inp=_make_input(command="npm --prefix apps/web test -- NavList")
        )
        assert result is not None
        assert "cwd" in result.message

    @pytest.mark.parametrize(
        "command",
        ["npm test", "npm run test", "npm install", "npm ci"],
    )
    def test_allows_generic_npm(self, validator: SkillRedirectValidator, command: str) -> None:
        result = validator.validate(inp=_make_input(command=command))
        assert result is None


# Make _YAML_PATH accessible for tests above
