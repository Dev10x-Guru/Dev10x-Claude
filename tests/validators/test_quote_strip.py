"""Tests for the quote-aware tokenization helper."""

from __future__ import annotations

import pytest

from dev10x.validators._quote_strip import quote_strip


class TestQuoteStrip:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            # Plain commands pass through unchanged
            ("git status", "git status"),
            # Single-quoted spans are inert and removed entirely
            ("echo 'hello $(cat /etc/passwd)'", "echo "),
            ("gh api graphql -f query='{viewer{login}}'", "gh api graphql -f query="),
            # Inside double quotes, content stays (dollar/backtick still active)
            ('echo "$(git rev-parse HEAD)"', 'echo "$(git rev-parse HEAD)"'),
            ('echo "$CLAUDE_PLUGIN_ROOT"', 'echo "$CLAUDE_PLUGIN_ROOT"'),
            # ANSI-C strings are removed entirely
            ("sort -t$'\\t' -k2 file", "sort -t -k2 file"),
            ("printf $'\\n' >> log", "printf  >> log"),
            # Backslash escapes drop the escape and the next char outside quotes
            ("echo \\$NOTREAL", "echo NOTREAL"),
            # Mixed: single-quoted inert subshell drops, unquoted survives
            (
                "echo 'safe $(rm -rf /)' && echo $(date)",
                "echo  && echo $(date)",
            ),
            # Unterminated single quote: rest of string treated as quoted
            ("echo 'oops", "echo "),
        ],
    )
    def test_strips_inert_spans(self, command: str, expected: str) -> None:
        assert quote_strip(command=command) == expected

    def test_double_quotes_preserve_subshells(self) -> None:
        # The $(cat ...) inside double quotes is genuinely active and must
        # remain visible to DX002 so it can block.
        result = quote_strip(command='gh api -f body="$(cat /tmp/file)"')
        assert "$(cat /tmp/file)" in result

    def test_single_quotes_hide_subshells(self) -> None:
        # The same construct inside single quotes is literal text and must
        # disappear so DX002 does not false-positive on it.
        result = quote_strip(command="echo 'literal $(cat /tmp/file)'")
        assert "$(cat" not in result

    def test_unterminated_ansi_c_consumes_rest(self) -> None:
        # No closing single quote on an ANSI-C literal — treat the remainder
        # as quoted so nothing leaks into the threat-pattern surface.
        result = quote_strip(command="echo $'unterminated\\t escape")
        assert result == "echo "

    def test_unterminated_double_quote_consumes_rest(self) -> None:
        # Same defensive behavior as single quotes / ANSI-C: an unterminated
        # double quote means the rest of the line is treated as quoted.
        result = quote_strip(command='echo "still open here')
        assert result == 'echo "still open here'

    def test_escape_inside_quotes(self) -> None:
        # Backslash inside a double-quoted span escapes the next character,
        # so an escaped closing quote does not end the span.
        result = quote_strip(command='echo "with \\" embedded" rest')
        assert "rest" in result

    def test_escape_inside_ansi_c(self) -> None:
        # Backslash inside ANSI-C escapes the next character — a quoted-out
        # closing single quote does not terminate the literal.
        result = quote_strip(command="echo $'has \\' inside' rest")
        assert "rest" in result

    def test_ansi_c_in_middle_of_command(self) -> None:
        # The fixed escape vanishes; surrounding tokens are preserved.
        result = quote_strip(command="awk -F$'\\t' '{print $1}' file.tsv")
        assert "$'" not in result
        assert "awk -F" in result
        assert "file.tsv" in result
