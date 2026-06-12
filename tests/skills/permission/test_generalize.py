"""Tests for prompt-time permission-rule shape generalization (GH-597)."""

from __future__ import annotations

import pytest

from dev10x.skills.permission.generalize import generalize_rule_shape


class TestOverBroad:
    """Verb-blind prefixes get narrowed to a safe subcommand, not bare ``*``."""

    @pytest.mark.parametrize(
        "rule,expected",
        [
            ("Bash(ip route *)", "Bash(ip route get:*)"),
            ("Bash(ip route:*)", "Bash(ip route get:*)"),
            ("Bash(ip addr *)", "Bash(ip addr show:*)"),
            ("Bash(systemctl *)", "Bash(systemctl status:*)"),
            ("Bash(kubectl *)", "Bash(kubectl get:*)"),
        ],
    )
    def test_narrows_destructive_prefix(self, rule: str, expected: str) -> None:
        assert generalize_rule_shape(rule) == expected

    def test_already_narrowed_prefix_untouched(self) -> None:
        # An explicit subcommand is already safe — leave it alone.
        assert generalize_rule_shape("Bash(ip route get:*)") == "Bash(ip route get:*)"


class TestOverNarrow:
    """Session-pinned wrapper scripts get stripped to ``script:*``."""

    @pytest.mark.parametrize(
        "rule,expected",
        [
            ("Bash(persist.sh a1b2c3d4 *)", "Bash(persist.sh:*)"),
            ("Bash(persist.sh session-9f3 *)", "Bash(persist.sh:*)"),
            ("Bash(detect-tracker.sh PAY-123)", "Bash(detect-tracker.sh:*)"),
            ("Bash(extract-session.sh 42)", "Bash(extract-session.sh:*)"),
        ],
    )
    def test_strips_session_arg(self, rule: str, expected: str) -> None:
        assert generalize_rule_shape(rule) == expected

    def test_known_pattern_generalizer_path(self) -> None:
        # Not a wrapper script — falls through to the post-hoc generalizer
        # (strips the origin ref), then gets a reusable wildcard.
        assert generalize_rule_shape("Bash(git reset --hard origin/main)") == (
            "Bash(git reset --hard:*)"
        )


class TestTooLiteral:
    """Bare exact strings get a ``:*`` wildcard so arg variations don't re-prompt."""

    @pytest.mark.parametrize(
        "rule,expected",
        [
            ("Bash(yarn build:x)", "Bash(yarn build:*)"),
            ("Bash(npm run lint:js)", "Bash(npm run lint:*)"),
            ("Bash(make)", "Bash(make:*)"),
        ],
    )
    def test_adds_wildcard(self, rule: str, expected: str) -> None:
        assert generalize_rule_shape(rule) == expected


class TestWellShaped:
    """Already-reusable rules pass through unchanged."""

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git log:*)",
            "Bash(docker compose up:*)",
            "mcp__plugin_Dev10x_cli__detect_tracker",
        ],
    )
    def test_unchanged(self, rule: str) -> None:
        assert generalize_rule_shape(rule) == rule

    def test_bare_command_without_wrapper(self) -> None:
        # No ``Bash(...)`` wrapper: still gets a wildcard if too literal.
        assert generalize_rule_shape("ip route *") == "ip route get:*"
