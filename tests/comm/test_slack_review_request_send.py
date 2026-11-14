"""GH-1567: the review-request `send` posts in-package, not via a skill path."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from dev10x.comm.skills.notifications import slack_review_request
from dev10x.core.domain.common.result import Result, err, ok


class FakeNotify:
    def __init__(self, *, result: Result[str]) -> None:
        self.result = result
        self.calls: list[dict[str, str]] = []

    def __call__(self, *, channel: str, message: str) -> Result[str]:
        self.calls.append({"channel": channel, "message": message})
        return self.result


def _args(*, message: str | None = None, message_file: Path | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        channel="C0EXAMPLE01",
        message=message,
        message_file=str(message_file) if message_file else None,
    )


class TestCmdSend:
    @pytest.fixture
    def sent(self, monkeypatch: pytest.MonkeyPatch) -> FakeNotify:
        fake = FakeNotify(result=ok("123.456"))
        monkeypatch.setattr(slack_review_request, "notify_slack", fake)
        return fake

    @pytest.fixture
    def failed(self, monkeypatch: pytest.MonkeyPatch) -> FakeNotify:
        fake = FakeNotify(result=err("channel_not_found"))
        monkeypatch.setattr(slack_review_request, "notify_slack", fake)
        return fake

    def test_posts_the_message_to_the_channel(
        self,
        sent: FakeNotify,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        slack_review_request.cmd_send(_args(message="Please review"))

        assert sent.calls == [{"channel": "C0EXAMPLE01", "message": "Please review"}]
        assert capsys.readouterr().out == "✅ Slack message sent successfully! ts=123.456\n"

    def test_reads_the_message_from_a_file(self, sent: FakeNotify, tmp_path: Path) -> None:
        body = tmp_path / "message.txt"
        body.write_text("From a file")

        slack_review_request.cmd_send(_args(message_file=body))

        assert sent.calls == [{"channel": "C0EXAMPLE01", "message": "From a file"}]

    def test_exits_when_the_post_fails(
        self,
        failed: FakeNotify,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exited:
            slack_review_request.cmd_send(_args(message="Please review"))

        assert (exited.value.code, capsys.readouterr().err) == (
            1,
            "❌ Slack notification failed: channel_not_found\n",
        )

    def test_exits_without_a_message(self, sent: FakeNotify) -> None:
        with pytest.raises(SystemExit) as exited:
            slack_review_request.cmd_send(_args())

        assert (exited.value.code, sent.calls) == (1, [])
