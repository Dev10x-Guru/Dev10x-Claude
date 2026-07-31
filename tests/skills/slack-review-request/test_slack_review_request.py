#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest>=8.0,<9"]
# ///
"""Tests for slack-review-request.py config and message functions."""

import importlib.util
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "slack_review_request",
    _repo_root / "skills" / "slack-review-request" / "scripts" / "slack-review-request.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

resolve_project_config = _mod.resolve_project_config
format_review_message = _mod.format_review_message
resolve_mention = _mod.resolve_mention


class TestResolveProjectConfig:
    @pytest.fixture()
    def config(self):
        return {
            "default_action": "ask",
            "projects": {
                "my-app": {
                    "channel": "C0EXAMPLE01",
                    "mentions": ["@backend-team"],
                },
                "internal-tools": {"skip": True},
            },
        }

    def test_known_project_returns_config(self, config):
        result = resolve_project_config(
            config=config,
            repo_name="my-app",
        )
        assert result["channel"] == "C0EXAMPLE01"
        assert result["mentions"] == ["@backend-team"]
        assert result["skip"] is False

    def test_skip_project(self, config):
        result = resolve_project_config(
            config=config,
            repo_name="internal-tools",
        )
        assert result["skip"] is True

    def test_unknown_project_with_ask_default(self, config):
        result = resolve_project_config(
            config=config,
            repo_name="unknown-repo",
        )
        assert result["skip"] is False
        assert result["ask"] is True

    def test_unknown_project_with_skip_default(self, config):
        config["default_action"] = "skip"
        result = resolve_project_config(
            config=config,
            repo_name="unknown-repo",
        )
        assert result["skip"] is True


class TestResolveMention:
    @pytest.fixture()
    def slack_config(self):
        return {
            "user_groups": {"@backend-team": "<!subteam^S0EXAMPLE>"},
            "users": {
                "alice": {"slack_id": "U0ALICE", "name": "Alice"},
            },
        }

    def test_resolves_user_group(self, slack_config):
        assert (
            resolve_mention(
                mention="@backend-team",
                slack_config=slack_config,
            )
            == "<!subteam^S0EXAMPLE>"
        )

    def test_resolves_user_by_at_name(self, slack_config):
        assert (
            resolve_mention(
                mention="@alice",
                slack_config=slack_config,
            )
            == "<@U0ALICE>"
        )

    def test_unresolved_returns_as_is(self, slack_config):
        assert (
            resolve_mention(
                mention="@unknown",
                slack_config=slack_config,
            )
            == "@unknown"
        )


class TestFormatReviewMessage:
    def test_basic_message(self):
        result = format_review_message(
            pr_number=42,
            repo="org/my-app",
            pr_url="https://github.com/org/my-app/pull/42",
            pr_title="Fix payment routing",
            jtbd=None,
            resolved_mentions=["<!subteam^S0EXAMPLE>"],
        )
        first_line = result.splitlines()[0]
        assert first_line.startswith("<!subteam^S0EXAMPLE> Please review")
        assert "<https://github.com/org/my-app/pull/42|my-app#42>" in first_line

    def test_message_with_jtbd(self):
        result = format_review_message(
            pr_number=42,
            repo="org/my-app",
            pr_url="https://github.com/org/my-app/pull/42",
            pr_title="Fix routing",
            jtbd="**When** reconciling, **wants to** see order",
            resolved_mentions=[],
        )
        assert "> *When* reconciling, *wants to* see order" in result

    def test_no_mentions_starts_with_please_review(self):
        result = format_review_message(
            pr_number=42,
            repo="org/my-app",
            pr_url="https://github.com/org/my-app/pull/42",
            pr_title="Fix routing",
            jtbd=None,
            resolved_mentions=[],
        )
        assert result.startswith("Please review")
