from __future__ import annotations

import pytest
from dev10x.domain.common.bash_tokens import (
    ANY_CASE_ENV_VAR_RE,
    ENV_VAR_RE,
    GIT_C_DIR_RE,
    GIT_C_PREFIX_RE,
    NestedCommand,
    UntokenizableCommandError,
    command_position_re,
    command_segments,
    command_units,
    nested_commands,
    split_tokens,
    strip_command_wrappers,
    strip_line_continuations,
    strip_quoted_spans,
)


class TestStripCommandWrappers:
    """GH-1630 review: guards must judge the program, not its wrapper."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("python -c x", ["python", "-c", "x"]),
            ("FOO=1 bar=2 python -c x", ["python", "-c", "x"]),
            ("env python -c x", ["python", "-c", "x"]),
            ("env -i -u HOME FOO=1 python -c x", ["python", "-c", "x"]),
            ("timeout 30 uv run python", ["uv", "run", "python"]),
            ("timeout -s KILL -k 5 30s bq query", ["bq", "query"]),
            ("nice -n 10 nohup python3 x.py", ["python3", "x.py"]),
            ("/usr/bin/env -- python3", ["python3"]),
            ("exec -a name bash -c x", ["bash", "-c", "x"]),
            ("command python -c x", ["python", "-c", "x"]),
            ("stdbuf -o L time -f %e python -c x", ["python", "-c", "x"]),
            ("timeout", []),
            ("env", []),
            ("git status", ["git", "status"]),
            ("sudo python -c x", ["python", "-c", "x"]),
            ("sudo -u postgres dropdb app", ["dropdb", "app"]),
            ("sudo -iu postgres dropdb app", ["dropdb", "app"]),
            ("sudo -u5 dropdb app", ["dropdb", "app"]),
            ("sudo -E --preserve-env=PATH timeout 5 ruff check", ["ruff", "check"]),
            ("doas -u app python -c x", ["python", "-c", "x"]),
            ("xargs -I {} -n 1 dropdb {}", ["dropdb", "{}"]),
            ("xargs -0r python", ["python"]),
            ("timeout -k5 30 python", ["python"]),
            (">/dev/null python -c x", ["python", "-c", "x"]),
            ("2> err.log python3 -c x", ["python3", "-c", "x"]),
            ("<in.txt &>>out.log sudo python -c x", ["python", "-c", "x"]),
        ],
    )
    def test_returns_the_program_actually_run(self, command: str, expected: list[str]) -> None:
        assert strip_command_wrappers(parts=command.split()) == expected


def _argvs(command: str) -> list[list[str]]:
    return [list(segment.argv) for segment in command_segments(command=command)]


class TestCommandSegments:
    """GH-1773: one segmenter splits on every shell operator."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("a;b", [["a"], ["b"]]),
            ("a & b", [["a"], ["b"]]),
            ("a&&b||c", [["a"], ["b"], ["c"]]),
            ("a|b|&c", [["a"], ["b"], ["c"]]),
            ("a\nb", [["a"], ["b"]]),
            ("(a) ; { b; }", [["a"], ["b"]]),
            ("echo $(python -c x)", [["echo", "$"], ["python", "-c", "x"]]),
            ("if dropdb x; then ruff check; fi", [["dropdb", "x"], ["ruff", "check"], ["fi"]]),
            ("! ruff check", [["ruff", "check"]]),
            ("echo 'a;b|c' \"d&e\"", [["echo", "a;b|c", "d&e"]]),
            ("echo 'line1\nline2'", [["echo", "line1\nline2"]]),
            ("git commit -m x \\\n  --amend", [["git", "commit", "-m", "x", "--amend"]]),
            ("cmd 2>&1 | tee f", [["cmd", "2>&1"], ["tee", "f"]]),
            ("echo x >&2", [["echo", "x", ">&2"]]),
            ("echo x &>f", [["echo", "x", "&>f"]]),
            ("true # note\npython -c y", [["true"], ["python", "-c", "y"]]),
            ("dropdb x # don't", [["dropdb", "x"]]),
            ("echo a#b", [["echo", "a#b"]]),
            ("echo ';' > f", [["echo", ";", ">", "f"]]),
            ("sed -e ';' -i f", [["sed", "-e", ";", "-i", "f"]]),
            (
                "find . \\( -name a \\) -exec rm {} \\;",
                [["find", ".", "(", "-name", "a", ")", "-exec", "rm", "{}", ";"]],
            ),
            ("echo '>' & dropdb x", [["echo", ">"], ["dropdb", "x"]]),
            ("echo x >| f", [["echo", "x", ">|", "f"]]),
            ("echo 'a'& dropdb x", [["echo", "a"], ["dropdb", "x"]]),
            ("drop\\\ndb x", [["dropdb", "x"]]),
            ('echo "a"&& dropdb x', [["echo", "a"], ["dropdb", "x"]]),
            ('echo "a\\"b" \'c\\d\'', [["echo", 'a"b', "c\\d"]]),
            ("cat <<EOF > f\nruff check .\nEOF\nls", [["cat", "<<EOF", ">", "f"], ["ls"]]),
            ("cat <<'EOF'\n$(rm x) don't\nEOF", [["cat", "<<EOF"]]),
            ("cat <<-EOF\n\tbody\n\tEOF\nls", [["cat", "<<-EOF"], ["ls"]]),
            ("cat << EOF\nbody\nEOF\nls", [["cat", "<<", "EOF"], ["ls"]]),
            ("cat <<<'x;y'", [["cat", "<<<x;y"]]),
            ("", []),
        ],
    )
    def test_splits_on_every_operator(self, command: str, expected: list[list[str]]) -> None:
        assert _argvs(command) == expected

    @pytest.mark.parametrize(
        ("command", "piped"),
        [
            ("a | b", [False, True]),
            ("a |& b", [False, True]),
            ("a ; b", [False, False]),
            ("a | (b)", [False, True]),
            ("a && b", [False, False]),
        ],
    )
    def test_marks_segments_that_read_a_pipe(self, command: str, piped: list[bool]) -> None:
        assert [s.is_piped for s in command_segments(command=command)] == piped

    def test_reports_the_opening_operator(self) -> None:
        openers = [s.opener for s in command_segments(command="a; b && c\nd")]

        assert openers == ["", ";", "&&", ";"]

    @pytest.mark.parametrize("command", ["echo 'unterminated", 'echo "unterminated'])
    def test_raises_on_untokenizable_input(self, command: str) -> None:
        with pytest.raises(UntokenizableCommandError):
            command_segments(command=command)


class TestCommandPositionRe:
    @pytest.mark.parametrize(
        "command",
        [
            "python -c 'x",
            "true;python -c 'x",
            "true & python -c 'x",
            "true\npython -c 'x",
            "(python -c 'x",
            "{ python -c 'x",
            "FOO=1 /usr/bin/python -c 'x",
            "sudo -E timeout 30 python -c 'x",
        ],
    )
    def test_matches_program_in_command_position(self, command: str) -> None:
        assert command_position_re(program="python").search(command)

    @pytest.mark.parametrize("command", ["grep -E 'a|b' bin/x.sh", "cat python.txt", "mypython"])
    def test_ignores_program_as_an_argument(self, command: str) -> None:
        assert command_position_re(program="sh|python").search(command) is None


class TestNestedCommands:
    """GH-1774: runners whose arguments are themselves a command."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("ssh host 'dropdb app'", [NestedCommand(command="dropdb app", remote=True)]),
            (
                "ssh -p 22 -i key host python -c x",
                [NestedCommand(command="python -c x", remote=True)],
            ),
            ("ssh db01 -t dropdb x", [NestedCommand(command="dropdb x", remote=True)]),
            ("ssh -vp 22 host dropdb x", [NestedCommand(command="dropdb x", remote=True)]),
            ("su postgres -c 'dropdb app'", [NestedCommand(command="dropdb app")]),
            ("su --command='python -c x' app", [NestedCommand(command="python -c x")]),
            ("su postgres -c'dropdb x'", [NestedCommand(command="dropdb x")]),
            ("su -lc 'dropdb x' postgres", [NestedCommand(command="dropdb x")]),
            ("runuser -l app -c 'dropdb x'", [NestedCommand(command="dropdb x")]),
            ("op run --env-file=.env -- psql -c x", [NestedCommand(command="psql -c x")]),
            (
                "find . -name x -exec sed -i s/a/b/ {} ; -exec rm {} +",
                [
                    NestedCommand(command="sed -i s/a/b/ '{}'"),
                    NestedCommand(command="rm '{}'"),
                ],
            ),
        ],
    )
    def test_returns_the_command_a_runner_executes(
        self, command: str, expected: list[NestedCommand]
    ) -> None:
        assert nested_commands(parts=split_tokens(command=command)) == expected

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("kubectl exec pg-0 -- dropdb app", "dropdb app"),
            ("kubectl exec mypod -n prod -- dropdb x", "dropdb x"),
            ("kubectl -n ns exec -c db pg-0 -- python -c x", "python -c x"),
            ("docker exec -u root c python -c x", "python -c x"),
            ("podman exec -it c sh -c x", "sh -c x"),
            ("docker run --rm postgres:16 dropdb -h h db", "dropdb -h h db"),
            ("docker compose exec db dropdb x", "dropdb x"),
            ("docker --context prod exec c dropdb x", "dropdb x"),
            ("nerdctl run img python -c x", "python -c x"),
        ],
    )
    def test_container_cli_candidates_include_the_command(
        self, command: str, expected: str
    ) -> None:
        nested = nested_commands(parts=split_tokens(command=command))

        assert expected in [candidate.command for candidate in nested]
        assert all(candidate.remote for candidate in nested)

    @pytest.mark.parametrize(
        "command",
        [
            "ssh host",
            "su postgres",
            "kubectl --",
            "op read op://vault/item",
            "find . -name x",
            "git status",
            "",
        ],
    )
    def test_no_command_when_none_is_run(self, command: str) -> None:
        nested = nested_commands(parts=split_tokens(command=command))

        assert [candidate for candidate in nested if candidate.command] == []


class TestCommandUnits:
    def test_runner_body_is_its_own_unit(self) -> None:
        assert command_units(command="cd x && ssh host 'python -c y'") == (
            "cd x && ssh host 'python -c y'",
            "python -c y",
        )

    def test_runner_inside_a_substitution_is_reached(self) -> None:
        units = command_units(command="echo $(sudo kubectl exec p -- dropdb app)")

        assert "dropdb app" in units

    def test_repeated_bodies_appear_once(self) -> None:
        units = command_units(command="echo $(ssh h x) $(ssh h x)")

        assert units.count("ssh h x") == 1

    @pytest.mark.parametrize("command", ["echo $(unclosed", "echo `unclosed"])
    def test_unbalanced_substitution_adds_nothing(self, command: str) -> None:
        assert command_units(command=command) == (command,)

    def test_remote_bodies_can_be_left_out(self) -> None:
        command = "su app -c 'ssh host python /srv/x.py'"

        assert command_units(command=command, include_remote=False) == (
            command,
            "ssh host python /srv/x.py",
        )

    def test_quote_split_runner_name_is_still_probed(self) -> None:
        assert "dropdb x" in command_units(command="s''sh h 'dropdb x'")

    def test_untokenizable_runner_unit_adds_nothing(self) -> None:
        assert command_units(command="ssh host 'unterminated") == ("ssh host 'unterminated",)


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


class TestStripQuotedSpans:
    def test_strips_single_quoted_span(self) -> None:
        assert strip_quoted_spans(command="echo 'a;b'") == "echo ''"

    def test_strips_double_quoted_span(self) -> None:
        assert strip_quoted_spans(command='echo "a;b"') == "echo ''"

    def test_strips_multiline_double_quoted_span(self) -> None:
        assert strip_quoted_spans(command='echo "line1\nline2"') == "echo ''"

    def test_strips_multiline_single_quoted_span(self) -> None:
        assert strip_quoted_spans(command="echo 'line1\nline2'") == "echo ''"

    def test_honours_escaped_double_quote(self) -> None:
        # The escaped `\"` must not end the span early.
        assert strip_quoted_spans(command='echo "she said \\"hi\\""') == "echo ''"

    def test_leaves_unquoted_text_alone(self) -> None:
        assert strip_quoted_spans(command="git status; git fetch") == "git status; git fetch"

    def test_strips_both_quote_types_in_one_command(self) -> None:
        result = strip_quoted_spans(command="grep 'a;b' file | echo \"c;d\"")
        assert result == "grep '' file | echo ''"


class TestStripLineContinuations:
    def test_joins_backslash_newline(self) -> None:
        result = strip_line_continuations(command="git commit -m foo \\\n  --author bar")
        assert "\n" not in result
        assert result.split() == ["git", "commit", "-m", "foo", "--author", "bar"]

    def test_leaves_bare_newline_alone(self) -> None:
        assert strip_line_continuations(command="git status\ngit fetch") == "git status\ngit fetch"

    def test_no_continuation_is_a_no_op(self) -> None:
        assert strip_line_continuations(command="git status") == "git status"
