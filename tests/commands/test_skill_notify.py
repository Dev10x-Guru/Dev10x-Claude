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
        assert "Provide --message, --message-file, or --card-file" in result.output

    def _capture_notify(
        self, monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]
    ) -> None:
        def fake_notify(
            *,
            space: str,
            message: str | None = None,
            cards: list[dict] | None = None,
            fallback_text: str | None = None,
            thread: str | None = None,
        ) -> Result[str]:
            captured.update(
                space=space,
                message=message,
                cards=cards,
                fallback_text=fallback_text,
                thread=thread,
            )
            return ok("spaces/A/messages/X")

        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(gchat_notify, "notify_gchat", fake_notify)

    def test_calls_notify_gchat(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}
        self._capture_notify(monkeypatch, captured)

        result = runner.invoke(
            cli,
            ["skill", "notify", "gchat-send", "--space", "tt-reviews", "--message", "hi"],
        )

        assert result.exit_code == 0, result.output
        assert captured["space"] == "tt-reviews"
        assert captured["message"] == "hi"
        assert captured["cards"] is None
        assert "spaces/A/messages/X" in result.output

    def test_card_title_wraps_body_in_a_panel(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}
        self._capture_notify(monkeypatch, captured)

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-send",
                "--space",
                "tt-reviews",
                "--message",
                "*hi*",
                "--card-title",
                "Nightly",
                "--card-subtitle",
                "run 4",
            ],
        )

        assert result.exit_code == 0, result.output
        cards = captured["cards"]
        assert isinstance(cards, list)
        assert cards[0]["card"]["header"] == {"title": "Nightly", "subtitle": "run 4"}
        assert cards[0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"] == (
            "<b>hi</b>"
        )
        # The body moved into the panel; duplicating it as text would double-post.
        assert captured["message"] is None

    def test_card_title_and_card_file_are_mutually_exclusive(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        card_file = tmp_path / "card.json"
        card_file.write_text("[]")

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-send",
                "--space",
                "s",
                "--message",
                "hi",
                "--card-title",
                "T",
                "--card-file",
                str(card_file),
            ],
        )
        assert result.exit_code != 0
        assert "not both" in result.output

    def test_card_subtitle_requires_card_title(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-send",
                "--space",
                "s",
                "--message",
                "hi",
                "--card-subtitle",
                "sub",
            ],
        )
        assert result.exit_code != 0
        assert "--card-subtitle requires --card-title" in result.output

    def test_card_file_posts_raw_json_alongside_the_message(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        captured: dict[str, object] = {}
        self._capture_notify(monkeypatch, captured)

        card_file = tmp_path / "card.json"
        card_file.write_text('[{"cardId": "c1", "card": {"sections": []}}]')

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-send",
                "--space",
                "s",
                "--message",
                "@team",
                "--card-file",
                str(card_file),
                "--fallback-text",
                "ping",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["cards"] == [{"cardId": "c1", "card": {"sections": []}}]
        assert captured["message"] == "@team"
        assert captured["fallback_text"] == "ping"

    def test_reads_message_from_file(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        captured: dict[str, object] = {}
        self._capture_notify(monkeypatch, captured)

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


class TestLoadCards:
    def _write(self, tmp_path: Path, content: str) -> Path:
        card_file = tmp_path / "card.json"
        card_file.write_text(content)
        return card_file

    def test_passes_through_a_cards_array(self, tmp_path: Path) -> None:
        from dev10x.commands.skill import _load_cards

        path = self._write(tmp_path, '[{"cardId": "c1", "card": {}}]')
        assert _load_cards(path) == [{"cardId": "c1", "card": {}}]

    def test_wraps_a_single_card_with_id(self, tmp_path: Path) -> None:
        from dev10x.commands.skill import _load_cards

        path = self._write(tmp_path, '{"cardId": "c1", "card": {"sections": []}}')
        assert _load_cards(path) == [{"cardId": "c1", "card": {"sections": []}}]

    def test_wraps_a_bare_card_object(self, tmp_path: Path) -> None:
        from dev10x.commands.skill import _load_cards

        path = self._write(tmp_path, '{"sections": []}')
        assert _load_cards(path) == [{"cardId": "dev10x-message", "card": {"sections": []}}]

    def test_rejects_malformed_json(self, tmp_path: Path) -> None:
        import click

        from dev10x.commands.skill import _load_cards

        path = self._write(tmp_path, "{not json")
        with pytest.raises(click.UsageError, match="not valid JSON"):
            _load_cards(path)

    def test_rejects_a_non_object_payload(self, tmp_path: Path) -> None:
        import click

        from dev10x.commands.skill import _load_cards

        path = self._write(tmp_path, '"just a string"')
        with pytest.raises(click.UsageError, match="cardsV2 array or a single card"):
            _load_cards(path)


class TestGchatSendThread:
    def test_forwards_thread_to_notify_gchat(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}
        TestGchatSend()._capture_notify(monkeypatch, captured)

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-send",
                "--space",
                "tt-reviews",
                "--message",
                "hi",
                "--thread",
                "spaces/A/threads/T1",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["thread"] == "spaces/A/threads/T1"

    def test_thread_defaults_to_none(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}
        TestGchatSend()._capture_notify(monkeypatch, captured)

        runner.invoke(
            cli,
            ["skill", "notify", "gchat-send", "--space", "tt-reviews", "--message", "hi"],
        )

        assert captured["thread"] is None


class TestGchatUpdate:
    def _capture_update(
        self, monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]
    ) -> None:
        def fake_update(
            *,
            message_name: str,
            message: str | None = None,
            cards: list[dict] | None = None,
            fallback_text: str | None = None,
        ) -> Result[str]:
            captured.update(
                message_name=message_name,
                message=message,
                cards=cards,
                fallback_text=fallback_text,
            )
            return ok(message_name)

        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(gchat_notify, "update_gchat_message", fake_update)

    def test_requires_a_body(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-update",
                "--message-name",
                "spaces/A/messages/X",
            ],
        )

        assert result.exit_code != 0
        assert "Provide --message, --message-file, or --card-file" in result.output

    def test_calls_update_gchat_message(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}
        self._capture_update(monkeypatch, captured)

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-update",
                "--message-name",
                "spaces/A/messages/X",
                "--message",
                "corrected",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["message_name"] == "spaces/A/messages/X"
        assert captured["message"] == "corrected"
        assert "Google Chat message updated" in result.output

    def test_card_title_wraps_the_replacement_body(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}
        self._capture_update(monkeypatch, captured)

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-update",
                "--message-name",
                "spaces/A/messages/X",
                "--message",
                "*hi*",
                "--card-title",
                "Nightly",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["message"] is None
        assert captured["cards"] is not None

    def test_maps_error_to_exit_1(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(
            gchat_notify,
            "update_gchat_message",
            lambda **kwargs: err("nope"),
        )

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-update",
                "--message-name",
                "spaces/A/messages/X",
                "--message",
                "hi",
            ],
        )

        assert result.exit_code == 1
        assert "nope" in result.output


class TestGchatDelete:
    def test_calls_delete_gchat_message(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(
            gchat_notify,
            "delete_gchat_message",
            lambda *, message_name: captured.update(message_name=message_name) or ok(message_name),
        )

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-delete",
                "--message-name",
                "spaces/A/messages/X",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["message_name"] == "spaces/A/messages/X"
        assert "Google Chat message deleted" in result.output

    def test_requires_message_name(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["skill", "notify", "gchat-delete"])

        assert result.exit_code != 0

    def test_maps_error_to_exit_1(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.skills.notifications import gchat_notify

        monkeypatch.setattr(
            gchat_notify,
            "delete_gchat_message",
            lambda **kwargs: err("denied"),
        )

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "gchat-delete",
                "--message-name",
                "spaces/A/messages/X",
            ],
        )

        assert result.exit_code == 1
        assert "denied" in result.output


def test_gchat_review_prepare_invokes_cmd_prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    from dev10x.commands import skill as skill_cmd
    from dev10x.skills.notifications import gchat_review_request

    called: dict = {}

    def fake_prepare(args) -> None:  # noqa: ANN001
        called["pr"] = args.pr
        called["repo"] = args.repo
        print('{"skip": false}')

    monkeypatch.setattr(gchat_review_request, "cmd_prepare", fake_prepare)
    runner = CliRunner()
    result = runner.invoke(
        skill_cmd.skill,
        ["notify", "gchat-review-prepare", "--pr", "42", "--repo", "org/app"],
    )
    assert result.exit_code == 0
    assert called == {"pr": 42, "repo": "org/app"}


def test_gchat_review_prepare_maps_gh_error_to_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    from dev10x.commands import skill as skill_cmd
    from dev10x.skills.notifications import gchat_review_request

    def boom(args) -> None:  # noqa: ANN001
        raise gchat_review_request.GhCommandError("gh pr view: not found")

    monkeypatch.setattr(gchat_review_request, "cmd_prepare", boom)
    runner = CliRunner()
    result = runner.invoke(
        skill_cmd.skill,
        ["notify", "gchat-review-prepare", "--pr", "1", "--repo", "org/app"],
    )
    assert result.exit_code == 1
    assert "not found" in result.output
