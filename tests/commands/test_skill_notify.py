"""Tests for `dev10x skill notify` subcommands (GH-313, GH-442)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.cli import cli
from dev10x.domain.common.result import Result, err, ok


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestNotifyGroupRegistration:
    def test_notify_group_exposed(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["skill", "notify", "--help"])

        assert result.exit_code == 0
        assert "slack-review-prepare" in result.output
        assert "slack-send" in result.output

    def test_slack_review_prepare_help(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-review-prepare", "--help"],
        )

        assert result.exit_code == 0
        assert "--pr" in result.output
        assert "--repo" in result.output

    def test_slack_send_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["skill", "notify", "slack-send", "--help"])

        assert result.exit_code == 0
        assert "--channel" in result.output
        assert "--message" in result.output
        assert "--message-file" in result.output
        assert "--thread-ts" in result.output
        assert "--workspace" in result.output


class TestSlackReviewPrepare:
    def test_delegates_to_cmd_prepare(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_cmd_prepare(args: object) -> None:
            captured["pr"] = args.pr  # type: ignore[attr-defined]
            captured["repo"] = args.repo  # type: ignore[attr-defined]

        from dev10x.skills.notifications import slack_review_request

        monkeypatch.setattr(slack_review_request, "cmd_prepare", fake_cmd_prepare)

        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-review-prepare", "--pr", "42", "--repo", "org/r"],
        )

        assert result.exit_code == 0, result.output
        assert captured == {"pr": 42, "repo": "org/r"}


class TestSlackSend:
    def test_requires_message_or_file(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-send", "--channel", "C123"],
        )

        assert result.exit_code != 0
        assert "Provide --message or --message-file" in result.output

    def test_calls_send_slack_message(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GH-442: slack-send must call send_slack_message, not subprocess the script."""
        captured: dict[str, object] = {}

        def fake_send(
            channel: str,
            message: str,
            thread_ts: str | None = None,
            **kwargs: object,
        ) -> Result[str]:
            captured["channel"] = channel
            captured["message"] = message
            captured["thread_ts"] = thread_ts
            return ok("1234567890.123456")

        from dev10x.skills.notifications import slack_notify

        monkeypatch.setattr(slack_notify, "send_slack_message", fake_send)
        monkeypatch.setattr(slack_notify, "set_workspace", lambda name: None)

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "slack-send",
                "--channel",
                "C123",
                "--message",
                "hello",
                "--thread-ts",
                "1.2",
                "--workspace",
                "aperture",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["channel"] == "C123"
        assert captured["message"] == "hello"
        assert captured["thread_ts"] == "1.2"
        assert "Slack message sent" in result.output

    def test_reads_message_from_file(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_send(channel: str, message: str, **kwargs: object) -> Result[str]:
            captured["message"] = message
            return ok("ts")

        from dev10x.skills.notifications import slack_notify

        monkeypatch.setattr(slack_notify, "send_slack_message", fake_send)

        msg_file = tmp_path / "msg.txt"
        msg_file.write_text("hello from file")

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "slack-send",
                "--channel",
                "C123",
                "--message-file",
                str(msg_file),
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["message"] == "hello from file"

    def test_exits_nonzero_on_send_failure(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.skills.notifications import slack_notify

        monkeypatch.setattr(
            slack_notify,
            "send_slack_message",
            lambda **kw: err("Failed to send Slack message: boom"),
        )

        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-send", "--channel", "C123", "--message", "x"],
        )

        assert result.exit_code == 1
        assert "Failed to send Slack message: boom" in result.output

    def test_works_without_skills_directory(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """GH-442: command must succeed even when skills/ dir is absent (uvx install)."""
        from dev10x.skills.notifications import slack_notify

        monkeypatch.setattr(
            slack_notify,
            "send_slack_message",
            lambda **kw: ok("ts.ok"),
        )

        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-send", "--channel", "C999", "--message", "hi"],
        )

        assert result.exit_code == 0, result.output
        assert "Slack message sent" in result.output


class TestGchatSend:
    def test_requires_message_or_file(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["skill", "notify", "gchat-send", "--space", "tt-reviews"],
        )

        assert result.exit_code != 0
        assert "Provide --message or --message-file" in result.output

    def test_calls_notify_gchat(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_notify(*, space: str, message: str) -> Result[str]:
            captured["space"] = space
            captured["message"] = message
            return ok("spaces/A/messages/X")

        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(gchat_notify, "notify_gchat", fake_notify)

        result = runner.invoke(
            cli,
            ["skill", "notify", "gchat-send", "--space", "tt-reviews", "--message", "hi"],
        )

        assert result.exit_code == 0, result.output
        assert captured["space"] == "tt-reviews"
        assert captured["message"] == "hi"
        assert "spaces/A/messages/X" in result.output

    def test_reads_message_from_file(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_notify(*, space: str, message: str) -> Result[str]:
            captured["message"] = message
            return ok("spaces/A/messages/X")

        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(gchat_notify, "notify_gchat", fake_notify)

        msg_file = tmp_path / "msg.txt"
        msg_file.write_text("hello from file")

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-send",
                "--space",
                "tt-reviews",
                "--message-file",
                str(msg_file),
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["message"] == "hello from file"

    def test_exits_nonzero_on_send_failure(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(
            gchat_notify,
            "notify_gchat",
            lambda **kw: err("no space"),
        )

        result = runner.invoke(
            cli,
            ["skill", "notify", "gchat-send", "--space", "bad", "--message", "hi"],
        )

        assert result.exit_code == 1
        assert "no space" in result.output
