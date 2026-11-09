from __future__ import annotations

import pytest
from dev10x.domain.common.bash_tokens import (
    ANY_CASE_ENV_VAR_RE,
    ENV_VAR_RE,
    GIT_C_DIR_RE,
    GIT_C_PREFIX_RE,
    NestedCommand,
    ProgramProbe,
    Redirect,
    UntokenizableCommandError,
    command_position_re,
    command_segments,
    command_units,
    is_simple_command,
    nested_commands,
    segment_programs,
    split_tokens,
    strip_command_wrappers,
    strip_line_continuations,
    strip_quoted_spans,
    tagged_command_units,
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
            ("setsid -f nice python -c x", ["python", "-c", "x"]),
            ("chroot /srv/root python -c x", ["python", "-c", "x"]),
            ("nsenter -t 1 -m python -c x", ["python", "-c", "x"]),
            ("pkexec --user root python -c x", ["python", "-c", "x"]),
            ("chroot --userspec root:root /srv python -c x", ["python", "-c", "x"]),
            ("env -uSTATE python -c x", ["python", "-c", "x"]),
        ],
    )
    def test_returns_the_program_actually_run(self, command: str, expected: list[str]) -> None:
        assert strip_command_wrappers(parts=command.split()) == expected

    @pytest.mark.parametrize(
        "command",
        [
            "env -S 'python -c x'",
            "env -iS 'python -c x'",
            "env -iS'python -c x'",
            "env --split-string 'python -c x'",
            "env --split-string='-i python -c x'",
            "env -u HOME -S 'FOO=1 python -c x'",
            "env --unset HOME -S 'python -c x'",
        ],
    )
    def test_splices_an_env_split_string(self, command: str) -> None:
        """GH-1798: `env -S` runs the words its string splits into."""
        assert strip_command_wrappers(parts=split_tokens(command=command)) == [
            "python",
            "-c",
            "x",
        ]


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
            ("echo $(python -c x)", [["echo", "$(...)"], ["python", "-c", "x"]]),
            # GH-1876: a substitution keeps its argv slot, glued to the
            # text around it, and the words after it continue its command.
            ("cp a $(pwd) b", [["cp", "a", "$(...)", "b"], ["pwd"]]),
            ("echo a$(b)c", [["echo", "a$(...)c"], ["b"]]),
            ("ls ./sub/$(date).py", [["ls", "./sub/$(...).py"], ["date"]]),
            ("echo $(a)$(b) `c`d", [["echo", "$(...)", "d"], ["a"], ["b"], ["c"]]),
            ("echo `date` x", [["echo", "$(...)", "x"], ["date"]]),
            ("echo `a", [["echo", "$(...)"], ["a"]]),
            ("echo \\$(date)", [["echo", "$"], ["date"]]),
            ("echo '$(date)' \"`a`\" ''", [["echo", "$(date)", "`a`", ""]]),
            ("x=$(cp a b)", [["x="], ["cp", "a", "b"]]),
            # NUL is the segmenter's substitution mark, never word text;
            # bash ends a `$'…'` word at it.
            ("echo $'a\\0b' $'\\0'x", [["echo", "a", "x"]]),
            ("$'rm\\0junk' -rf x", [["rm", "-rf", "x"]]),
            ("echo $'a\\012b' $'\\101' $'\\0\\'y'z", [["echo", "a\nb", "A", "z"]]),
            ("r\0m -rf x", [["rm", "-rf", "x"]]),
            # A real pipe or background `&` in a case arm is no pattern list.
            (
                "case x in a) ls | if b; then c; fi;; esac",
                [["case", "x", "in", "a"], ["ls"], ["b"], ["c"]],
            ),
            (
                "case x in a) sleep 1 & if b; then c; fi;; esac",
                [["case", "x", "in", "a"], ["sleep", "1"], ["b"], ["c"]],
            ),
            # A substitution at a word's edge, or before the program,
            # never hides the literal text a guard judges.
            ("$(true) cp x y", [["cp", "x", "y"], ["true"]]),
            ("$(a) `b` cp x y", [["cp", "x", "y"], ["a"], ["b"]]),
            ("$(:)psql -c q", [["psql", "-c", "q"], [":"]]),
            ("cp x docs/y.py$(:)", [["cp", "x", "docs/y.py"], [":"]]),
            ("cp x $(pwd)docs/y.py", [["cp", "x", "docs/y.py"], ["pwd"]]),
            ("cp x a$(b)\\\nc", [["cp", "x", "a$(...)c"], ["b"]]),
            # A substitution glued to a redirect target is part of it.
            ("echo a>f$(b)", [["echo", "a"], ["b"]]),
            ("> o$(x) cp a b", [["cp", "a", "b"], ["x"]]),
            (">o$(x)p cp a b", [["cp", "a", "b"], ["x"]]),
            ("> `x`p cp a b", [["cp", "a", "b"], ["x"]]),
            ("if dropdb x; then ruff check; fi", [["dropdb", "x"], ["ruff", "check"]]),
            (
                "for f in a; do ruff check $f; done",
                [["for", "f", "in", "a"], ["ruff", "check", "$f"]],
            ),
            ("echo fi done esac 'fi'", [["echo", "fi", "done", "esac", "fi"]]),
            ("'done'", [["done"]]),
            ("! ruff check", [["ruff", "check"]]),
            ("echo 'a;b|c' \"d&e\"", [["echo", "a;b|c", "d&e"]]),
            ("echo 'line1\nline2'", [["echo", "line1\nline2"]]),
            ("git commit -m x \\\n  --amend", [["git", "commit", "-m", "x", "--amend"]]),
            ("cmd 2>&1 | tee f", [["cmd"], ["tee", "f"]]),
            ("echo x >&2", [["echo", "x"]]),
            ("echo x &>f", [["echo", "x"]]),
            ("true # note\npython -c y", [["true"], ["python", "-c", "y"]]),
            ("dropdb x # don't", [["dropdb", "x"]]),
            ("echo a#b", [["echo", "a#b"]]),
            ("echo ';' > f", [["echo", ";"]]),
            ("sed -e ';' -i f", [["sed", "-e", ";", "-i", "f"]]),
            (
                "find . \\( -name a \\) -exec rm {} \\;",
                [["find", ".", "(", "-name", "a", ")", "-exec", "rm", "{}", ";"]],
            ),
            ("echo '>' & dropdb x", [["echo", ">"], ["dropdb", "x"]]),
            ("echo x >| f", [["echo", "x"]]),
            ("echo 'a'& dropdb x", [["echo", "a"], ["dropdb", "x"]]),
            ("drop\\\ndb x", [["dropdb", "x"]]),
            ('echo "a"&& dropdb x', [["echo", "a"], ["dropdb", "x"]]),
            ('echo "a\\"b" \'c\\d\'', [["echo", 'a"b', "c\\d"]]),
            ("cat <<EOF > f\nruff check .\nEOF\nls", [["cat"], ["ls"]]),
            ("cat <<'EOF'\n$(rm x) don't\nEOF", [["cat"]]),
            ("cat <<-EOF\n\tbody\n\tEOF\nls", [["cat"], ["ls"]]),
            ("cat << EOF\nbody\nEOF\nls", [["cat"], ["ls"]]),
            ("cat<<EOF\nruff check .\nEOF\nls", [["cat"], ["ls"]]),
            ("cat 0<<EOF\nruff check .\nEOF\nls", [["cat"], ["ls"]]),
            ("cat <<<'x;y'", [["cat"]]),
            ("", []),
        ],
    )
    def test_splits_on_every_operator(self, command: str, expected: list[list[str]]) -> None:
        assert _argvs(command) == expected


class TestRedirects:
    """GH-1798: the scanner owns the one redirect grammar."""

    @pytest.mark.parametrize(
        ("command", "argv", "redirects"),
        [
            ("python >/dev/null -c x", ["python", "-c", "x"], [(">", "/dev/null")]),
            (">/dev/null python -c x", ["python", "-c", "x"], [(">", "/dev/null")]),
            ("echo a>f", ["echo", "a"], [(">", "f")]),
            ("echo 'a'>f", ["echo", "a"], [(">", "f")]),
            ("echo a2>f", ["echo", "a2"], [(">", "f")]),
            ("cmd 2> err 3>&1", ["cmd"], [("2>", "err"), ("3>&", "1")]),
            ("cmd &>> log <&0 >| f", ["cmd"], [("&>>", "log"), ("<&", "0"), (">|", "f")]),
            ("cmd a&>f", ["cmd", "a"], [("&>", "f")]),
            ("cmd >f>g", ["cmd"], [(">", "f"), (">", "g")]),
            ("cat << 'EOF'\nbody\nEOF", ["cat"], [("<<", "EOF")]),
            ("cat <<<x", ["cat"], [("<<<", "x")]),
            ("echo '>' \\> \">\"", ["echo", ">", ">", ">"], []),
            ("> f", [], [(">", "f")]),
            ("cmd >", ["cmd"], [(">", "")]),
            ("cmd > ; ls", ["cmd"], [(">", "")]),
        ],
    )
    def test_redirects_leave_argv(
        self, command: str, argv: list[str], redirects: list[tuple[str, str]]
    ) -> None:
        segment = command_segments(command=command)[0]

        assert list(segment.argv) == argv
        assert [(r.operator, r.target) for r in segment.redirects] == redirects

    @pytest.mark.parametrize(
        ("operator", "writes", "inline_text"),
        [
            (">", True, False),
            ("2>>", True, False),
            ("&>", True, False),
            ("<", False, False),
            ("<<", False, True),
            ("0<<-", False, True),
            ("<<<", False, True),
        ],
    )
    def test_classifies_the_operator(self, operator: str, writes: bool, inline_text: bool) -> None:
        redirect = Redirect(operator=operator)

        assert (redirect.writes, redirect.feeds_inline_text) == (writes, inline_text)

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("{ echo hi; } > f", [(["echo", "hi"], [(">", "f")]), ([], [(">", "f")])]),
            ("(cat a b) > f", [(["cat", "a", "b"], [(">", "f")]), ([], [(">", "f")])]),
            ("(echo hi)>f", [(["echo", "hi"], [(">", "f")]), ([], [(">", "f")])]),
            (
                "{ a; b; } 2>/dev/null >> f",
                [
                    (["a"], [("2>", "/dev/null"), (">>", "f")]),
                    (["b"], [("2>", "/dev/null"), (">>", "f")]),
                    ([], [("2>", "/dev/null"), (">>", "f")]),
                ],
            ),
            (
                "{ { a; } > f; } > g",
                [
                    (["a"], [(">", "f"), (">", "g")]),
                    ([], [(">", "f"), (">", "g")]),
                    ([], [(">", "g")]),
                ],
            ),
            ("(a | b) > f", [(["a"], [(">", "f")]), (["b"], [(">", "f")]), ([], [(">", "f")])]),
            # Only a redirect that directly follows the closing brace or
            # paren belongs to the group.
            ("{ a; } ; > f", [(["a"], []), ([], [(">", "f")])]),
            ("(a); > f", [(["a"], []), ([], [(">", "f")])]),
            ("(a) b > f", [(["a"], []), (["b"], [(">", "f")])]),
            ("(a) | b > f", [(["a"], []), (["b"], [(">", "f")])]),
            ("{ a; } && b > f", [(["a"], []), (["b"], [(">", "f")])]),
            ("a; } > f", [(["a"], []), ([], [(">", "f")])]),
            # A quoted brace is a word, never a group boundary.
            (
                "{ echo hi; '}'; } > f",
                [(["echo", "hi"], [(">", "f")]), (["}"], [(">", "f")]), ([], [(">", "f")])],
            ),
            (
                '{ echo hi; "{"; } > f',
                [(["echo", "hi"], [(">", "f")]), (["{"], [(">", "f")]), ([], [(">", "f")])],
            ),
            ("\\{ a; } > f", [(["{", "a"], []), ([], [(">", "f")])]),
            # A `)` ending a `case` pattern closes no group.
            (
                "{ echo hi; case x in x) :;; esac; } > f",
                [
                    (["echo", "hi"], [(">", "f")]),
                    (["case", "x", "in", "x"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "( echo hi; case x in (x) :;; esac ) > f",
                [
                    (["echo", "hi"], [(">", "f")]),
                    (["case", "x", "in"], [(">", "f")]),
                    (["x"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "( echo hi; case x in x) :;; esac ) > f",
                [
                    (["echo", "hi"], [(">", "f")]),
                    (["case", "x", "in", "x"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "( case x in a) :;; b) :;; esac ) > f",
                [
                    (["case", "x", "in", "a"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    (["b"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "( case x in a|b) :;; esac ) > f",
                [
                    (["case", "x", "in", "a"], [(">", "f")]),
                    (["b"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "( case x in\n x) :;; esac ) > f",
                [
                    (["case", "x", "in"], [(">", "f")]),
                    (["x"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "(echo hi; 'case') > f",
                [(["echo", "hi"], [(">", "f")]), (["case"], [(">", "f")]), ([], [(">", "f")])],
            ),
            # A compound command's redirect reaches every command inside,
            # its condition or header included (GH-1876).
            (
                "if true; then echo hi; fi > f",
                [(["true"], [(">", "f")]), (["echo", "hi"], [(">", "f")]), ([], [(">", "f")])],
            ),
            (
                "if a; then b; else c; fi 2>/dev/null",
                [
                    (["a"], [("2>", "/dev/null")]),
                    (["b"], [("2>", "/dev/null")]),
                    (["c"], [("2>", "/dev/null")]),
                    ([], [("2>", "/dev/null")]),
                ],
            ),
            (
                "while read l; do echo $l; done > f",
                [
                    (["read", "l"], [(">", "f")]),
                    (["echo", "$l"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "until false; do echo hi; done >> f",
                [(["false"], [(">>", "f")]), (["echo", "hi"], [(">>", "f")]), ([], [(">>", "f")])],
            ),
            (
                "for x in a b; do echo $x; done > f",
                [
                    (["for", "x", "in", "a", "b"], [(">", "f")]),
                    (["echo", "$x"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "case x in a) echo hi;; esac > f",
                [
                    (["case", "x", "in", "a"], [(">", "f")]),
                    (["echo", "hi"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "for x in a; do if b; then c; fi > g; done > f",
                [
                    (["for", "x", "in", "a"], [(">", "f")]),
                    (["b"], [(">", "g"), (">", "f")]),
                    (["c"], [(">", "g"), (">", "f")]),
                    ([], [(">", "g"), (">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "echo $(if a; then b; fi) > f",
                [(["echo", "$(...)"], [(">", "f")]), (["a"], []), (["b"], [])],
            ),
            # A reserved word in pattern position names a pattern.
            (
                "case x in a) echo hi;; if) :;; esac > f",
                [
                    (["case", "x", "in", "a"], [(">", "f")]),
                    (["echo", "hi"], [(">", "f")]),
                    (["if"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "case x in\n fi) echo hi;; esac > f",
                [
                    (["case", "x", "in"], [(">", "f")]),
                    (["fi"], [(">", "f")]),
                    (["echo", "hi"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "case x in (done) echo hi;; esac > f",
                [
                    (["case", "x", "in"], [(">", "f")]),
                    (["done"], [(">", "f")]),
                    (["echo", "hi"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "case x in a) if b; then c; fi;; esac > f",
                [
                    (["case", "x", "in", "a"], [(">", "f")]),
                    (["b"], [(">", "f")]),
                    (["c"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "case x in\n\n  a) echo hi ;;\n\n  if) : ;;\nesac > f",
                [
                    (["case", "x", "in"], [(">", "f")]),
                    (["a"], [(">", "f")]),
                    (["echo", "hi"], [(">", "f")]),
                    (["if"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "case x in a|if) echo hi;; b) :;; (c|done) :;; esac > f",
                [
                    (["case", "x", "in", "a"], [(">", "f")]),
                    (["if"], [(">", "f")]),
                    (["echo", "hi"], [(">", "f")]),
                    (["b"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    (["c"], [(">", "f")]),
                    (["done"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            (
                "case x in a) echo hi;& if) :;;& fi) :;; esac > f",
                [
                    (["case", "x", "in", "a"], [(">", "f")]),
                    (["echo", "hi"], [(">", "f")]),
                    (["if"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    (["fi"], [(">", "f")]),
                    ([":"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            # Only a redirect right after the closer belongs to the group.
            ("if a; then b; fi; > f", [(["a"], []), (["b"], []), ([], [(">", "f")])]),
            ("if a; then b; fi; c > f", [(["a"], []), (["b"], []), (["c"], [(">", "f")])]),
            ("a; fi > f", [(["a"], []), ([], [(">", "f")])]),
            ("{ a; fi > f", [(["a"], []), ([], [(">", "f")])]),
            ("while a; do b; esac > f", [(["a"], []), (["b"], []), ([], [(">", "f")])]),
            ("echo fi > f", [(["echo", "fi"], [(">", "f")])]),
            # A substitution's redirect belongs to the command holding it,
            # and the words after it continue that command (GH-1876).
            ("echo $(date) > f", [(["echo", "$(...)"], [(">", "f")]), (["date"], [])]),
            ("ls $(cat a) > f", [(["ls", "$(...)"], [(">", "f")]), (["cat", "a"], [])]),
            (
                "echo $(date) more > f",
                [(["echo", "$(...)", "more"], [(">", "f")]), (["date"], [])],
            ),
            (
                "echo $(a) $(b) > f",
                [(["echo", "$(...)", "$(...)"], [(">", "f")]), (["a"], []), (["b"], [])],
            ),
            (
                "echo $(a $(b)) c > f",
                [(["echo", "$(...)", "c"], [(">", "f")]), (["a", "$(...)"], []), (["b"], [])],
            ),
            ("$(a) b > f", [(["b"], [(">", "f")]), (["a"], [])]),
            # Arithmetic scans as `$(` then `(`; both closers balance.
            ("echo $((1+2)) > f", [(["echo", "$(...)"], [(">", "f")]), (["1+2"], [])]),
            ("x=$((a+b)) c > f", [(["x=", "c"], [(">", "f")]), (["a+b"], [])]),
            (">o$(x)p cp a b", [(["cp", "a", "b"], [(">", "o$(p")]), (["x"], [])]),
            ("cat <(true) > f", [(["cat"], [("<", ""), (">", "f")]), (["true"], [])]),
            ("cat < $(true) > f", [(["cat"], [("<", "$("), (">", "f")]), (["true"], [])]),
            ("cat < <(a) > f", [(["cat"], [("<", "<("), (">", "f")]), (["a"], [])]),
            ("echo > >(a) > f", [(["echo"], [(">", ">("), (">", "f")]), (["a"], [])]),
            ("echo >$(a)", [(["echo"], [(">", "$(")]), (["a"], [])]),
            ("echo $(a >) b", [(["echo", "$(...)", "b"], []), (["a"], [(">", "")])]),
            # Backticks are a substitution too.
            ("echo `date` > f", [(["echo", "$(...)"], [(">", "f")]), (["date"], [])]),
            (
                "echo `a` `b` c > f",
                [(["echo", "$(...)", "$(...)", "c"], [(">", "f")]), (["a"], []), (["b"], [])],
            ),
            ("echo > `a`", [(["echo"], [(">", "`")]), (["a"], [])]),
            ("echo > `a`b", [(["echo"], [(">", "`b")]), (["a"], [])]),
            ("echo `a >` b", [(["echo", "$(...)", "b"], []), (["a"], [(">", "")])]),
            # The holder stops at the next operator.
            (
                "echo $(a); { b; } c > f",
                [(["echo", "$(...)"], []), (["a"], []), (["b"], []), (["c"], [(">", "f")])],
            ),
            ("a | $(b) > f", [(["a"], []), ([], [(">", "f")]), (["b"], [])]),
            # A reserved word after a substitution is an argument.
            (
                "(echo $(date) case) > f",
                [
                    (["echo", "$(...)", "case"], [(">", "f")]),
                    (["date"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            ("(echo case) > f", [(["echo", "case"], [(">", "f")]), ([], [(">", "f")])]),
            (
                "( case x in x) 'esac';; esac ) > f",
                [
                    (["case", "x", "in", "x"], [(">", "f")]),
                    (["esac"], [(">", "f")]),
                    ([], [(">", "f")]),
                ],
            ),
            # A closer with no matching opener attributes nothing.
            ("a) > f", [(["a"], []), ([], [(">", "f")])]),
            ("{ a; ) > f", [(["a"], []), ([], [(">", "f")])]),
            ("(a; } > f", [(["a"], []), ([], [(">", "f")])]),
        ],
    )
    def test_attributes_a_group_redirect_to_the_commands_inside(
        self, command: str, expected: list[tuple[list[str], list[tuple[str, str]]]]
    ) -> None:
        # GH-1816: `{ echo hi; } > f` writes `f` through the group's
        # redirect, which the scanner put on a segment with no program.
        segments = command_segments(command=command)

        assert [
            (list(s.argv), [(r.operator, r.target) for r in s.redirects]) for s in segments
        ] == expected


class TestSegmentPrograms:
    def test_strips_wrappers_and_skips_empty_segments(self) -> None:
        programs = segment_programs(command="FOO=1; > f; sudo -u a python -c x | wc")

        assert [parts for _, parts in programs] == [["python", "-c", "x"], ["wc"]]

    def test_keeps_the_segment_for_its_redirects(self) -> None:
        [(segment, _)] = segment_programs(command="python 2>/dev/null")

        assert segment.redirects == (Redirect(operator="2>", target="/dev/null"),)

    def test_raises_on_untokenizable_input(self) -> None:
        with pytest.raises(UntokenizableCommandError):
            segment_programs(command="echo 'x")


class TestIsSimpleCommand:
    """GH-1795: the precondition for a whole-string auto-approval."""

    @pytest.mark.parametrize(
        "command", ["git status", "uv run pytest -k 'a;b'", "nc -zv host 22 2>/dev/null"]
    )
    def test_one_command_is_simple(self, command: str) -> None:
        assert is_simple_command(command=command)

    @pytest.mark.parametrize(
        "command",
        [
            "foo && rm -rf ~",
            "foo; bar",
            "foo | bar",
            "foo\nbar",
            "echo $(rm x)",
            "ssh h 'rm -rf ~'",
            "foo 'unterminated",
            "",
        ],
    )
    def test_anything_else_is_not(self, command: str) -> None:
        assert not is_simple_command(command=command)


class TestProgramProbe:
    """GH-1798: one boundary rule for every guard's pre-filter."""

    @pytest.mark.parametrize(
        "command",
        [
            "bq query x",
            "b''q query",
            "b\\q query",
            "su u -c'bq query'",
            "/opt/bin/bq ls",
            "$'\\142q' query",
            "$'\\'' x; $'\\142'q query",
            "$'\\142q' 'unterminated",
        ],
    )
    def test_finds_the_program_however_it_is_quoted(self, command: str) -> None:
        assert ProgramProbe.for_program(program="bq").found_in(command=command)

    @pytest.mark.parametrize(
        "command",
        ["bqtool x", "echo bqx", "git status", "printf $'\\101'; echo x", "$'" * 3000],
    )
    def test_needs_a_trailing_boundary(self, command: str) -> None:
        assert not ProgramProbe.for_program(program="bq").found_in(command=command)

    def test_accepts_alternatives(self) -> None:
        probe = ProgramProbe.for_program(program="dropdb|createdb")

        assert probe.found_in(command="c''reatedb app")

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

    @pytest.mark.parametrize(
        "command",
        ["echo 'unterminated", 'echo "unterminated', "echo $'a\\0b"],
    )
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
            "sudo -u app python -c 'x",
            "doas -u app -C conf python -c 'x",
            "ssh host python -c 'x",
            "ssh -p 22 db01 python -c 'x",
            "su app -c 'python -c \"x",
            ">/dev/null python -c 'x",
            "2> err.log FOO=1 python -c 'x",
            "true; > out python -c 'x",
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
            ("su -lcdropdb postgres", [NestedCommand(command="dropdb")]),
            ("su -l postgres", []),
            ("flock -n -- /tmp/l dropdb x", [NestedCommand(command="dropdb x")]),
            ("flock /tmp/l -c 'dropdb x'", [NestedCommand(command="dropdb x")]),
            ("watch -n 5 dropdb x", [NestedCommand(command="dropdb x")]),
            ("eval dropdb x", [NestedCommand(command="dropdb x")]),
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

    def test_redirect_stays_out_of_a_runner_body(self) -> None:
        assert command_units(command="ssh host 'dropdb x' > out.log") == (
            "ssh host 'dropdb x' > out.log",
            "dropdb x",
        )


class TestTaggedCommandUnits:
    """GH-1798: units and their remote flag come from one pass."""

    def test_tags_each_unit(self) -> None:
        command = "su app -c 'ssh host python /srv/x.py'"

        assert tagged_command_units(command=command) == (
            NestedCommand(command=command),
            NestedCommand(command="ssh host python /srv/x.py"),
            NestedCommand(command="python /srv/x.py", remote=True),
        )

    def test_runner_inside_a_remote_body_stays_remote(self) -> None:
        units = tagged_command_units(command="ssh h \"su u -c 'python /srv/x.py'\"")

        assert NestedCommand(command="python /srv/x.py", remote=True) in units

    def test_one_local_path_makes_a_unit_local(self) -> None:
        units = tagged_command_units(command="ssh h 'python /a.py'; su u -c 'python /a.py'")

        assert NestedCommand(command="python /a.py") in units
        assert NestedCommand(command="python /a.py", remote=True) not in units

    def test_blank_substitution_adds_no_unit(self) -> None:
        assert tagged_command_units(command="echo $( )") == (NestedCommand(command="echo $( )"),)

    def test_agrees_with_command_units(self) -> None:
        command = "echo $(ssh h 'dropdb x') && kubectl exec p -- psql"

        assert [unit.command for unit in tagged_command_units(command=command)] == list(
            command_units(command=command)
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
