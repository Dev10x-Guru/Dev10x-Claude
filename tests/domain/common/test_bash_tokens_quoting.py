"""GH-1795 review: the scanner reads ANSI-C `$'…'` quoting as bash does."""

from __future__ import annotations

import pytest
from dev10x.domain.common.bash_tokens import (
    Redirect,
    UntokenizableCommandError,
    command_segments,
    is_simple_command,
)


def _argvs(command: str) -> list[list[str]]:
    return [list(segment.argv) for segment in command_segments(command=command)]


class TestAnsiCQuoting:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("echo $'it\\'s' ; rm x", [["echo", "it's"], ["rm", "x"]]),
            (
                "pytest $'\\''; rm -rf ~; $'\\''",
                [["pytest", "'"], ["rm", "-rf", "~"], ["'"]],
            ),
            ("printf $'a\\tb\\n'", [["printf", "a\tb\n"]]),
            ("echo $'a;b|c'", [["echo", "a;b|c"]]),
            ("echo \"$'x'\"", [["echo", "$'x'"]]),
        ],
    )
    def test_splits_as_bash_does(self, command: str, expected: list[list[str]]) -> None:
        assert _argvs(command) == expected

    def test_unterminated_ansi_c_quote_is_untokenizable(self) -> None:
        with pytest.raises(UntokenizableCommandError):
            command_segments(command="echo $'oops")

    def test_quote_split_chain_is_not_simple(self) -> None:
        assert not is_simple_command(command="uv run --frozen pytest $'\\''; rm -rf ~; $'\\''")

    def test_carriage_return_is_not_a_blank(self) -> None:
        assert _argvs("git\rstatus") == [["git\rstatus"]]


class TestTouchesNoFile:
    @pytest.mark.parametrize(
        ("redirect", "expected"),
        [
            (Redirect(operator="2>", target="/dev/null"), True),
            (Redirect(operator="<", target="/dev/null"), True),
            (Redirect(operator="2>&", target="1"), True),
            (Redirect(operator=">&", target="-"), True),
            (Redirect(operator=">", target="out.txt"), False),
            (Redirect(operator=">&", target="out.txt"), False),
            (Redirect(operator="<<<", target="/dev/null"), False),
        ],
    )
    def test_classifies(self, redirect: Redirect, expected: bool) -> None:
        assert redirect.touches_no_file is expected

    @pytest.mark.parametrize(
        "command", ["pytest > ~/.bashrc", "pytest >> ~/.ssh/authorized_keys", "cat < .env"]
    )
    def test_a_file_redirect_is_not_simple(self, command: str) -> None:
        assert not is_simple_command(command=command)
