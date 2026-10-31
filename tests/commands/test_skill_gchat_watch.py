"""CLI: `dev10x skill notify gchat-watch` and `gchat-send --watch` (GH-1612, GH-1682)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from click.testing import CliRunner
from click.testing import Result as CliResult
from dev10x.domain.common.result import Result, err, ok

from dev10x.cli import cli
from dev10x.comm.skills.notifications import gchat_notify, gchat_watch
from dev10x.comm.skills.notifications.gchat_notify import PostedMessage
from dev10x.comm.skills.notifications.gchat_watch import PollReport, Watch, WatchEvent

ARMED = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
WATCH = Watch(
    id="S.T",
    space="spaces/S",
    thread="spaces/S/threads/T",
    notify=("me",),
    notify_roles=("tt-backend",),
    route=False,
    mode="reply",
    armed_at=ARMED,
    expires_at=ARMED + timedelta(hours=24),
)
ARMED_LINE = (
    "ARMED S.T spaces/S/threads/T mode=reply notify=me,role:tt-backend route=no "
    "expires=2026-10-31T12:00:00+00:00"
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def invoke(runner: CliRunner, *args: str) -> CliResult:
    return runner.invoke(cli, ["skill", "notify", *args])


class TestGchatSendWatch:
    @pytest.fixture
    def armed(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def fake_post(**kwargs: Any) -> Result[PostedMessage]:
            captured["post"] = kwargs
            return ok(PostedMessage(name="spaces/S/messages/M", thread="spaces/S/threads/T"))

        def fake_arm(**kwargs: Any) -> Result[Watch]:
            captured["arm"] = kwargs
            return ok(WATCH)

        monkeypatch.setattr(gchat_notify, "notify_gchat_detailed", fake_post)
        monkeypatch.setattr(gchat_watch, "arm_watch", fake_arm)
        return captured

    def test_arms_a_watch_on_the_posted_thread(
        self, runner: CliRunner, armed: dict[str, Any]
    ) -> None:
        result = invoke(
            runner,
            "gchat-send",
            "--space",
            "rev",
            "--message",
            "question?",
            "--watch",
            "--notify",
            "me",
            "--notify-role",
            "tt-backend",
            "--watch-mode",
            "ttl",
        )

        assert result.exit_code == 0, result.output
        assert armed["post"]["message"] == "question?"
        assert armed["arm"] == {
            "thread": "spaces/S/threads/T",
            "notify": ("me",),
            "notify_roles": ("tt-backend",),
            "mode": "ttl",
            "own_message_names": ("spaces/S/messages/M",),
        }
        assert ARMED_LINE in result.output

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--watch"], "--watch needs at least one --notify"),
            (["--notify", "me"], "only apply with --watch"),
        ],
    )
    def test_watch_flags_must_come_together(
        self, runner: CliRunner, args: list[str], message: str
    ) -> None:
        result = invoke(runner, "gchat-send", "--space", "rev", "--message", "hi", *args)

        assert result.exit_code == 2
        assert message in result.output

    @pytest.mark.parametrize(
        ("posted", "armed", "message"),
        [
            (err("HTTP 403"), ok(WATCH), "HTTP 403"),
            (ok(PostedMessage(name="spaces/S/messages/M", thread=None)), ok(WATCH), "no thread"),
            (
                ok(PostedMessage(name="spaces/S/messages/M", thread="spaces/S/threads/T")),
                err("store locked"),
                "the watch was not armed: store locked",
            ),
        ],
    )
    def test_failures_exit_nonzero(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        posted: Result[PostedMessage],
        armed: Result[Watch],
        message: str,
    ) -> None:
        monkeypatch.setattr(gchat_notify, "notify_gchat_detailed", lambda **_: posted)
        monkeypatch.setattr(gchat_watch, "arm_watch", lambda **_: armed)

        result = invoke(
            runner, "gchat-send", "--space", "rev", "--message", "hi", "--watch", "--notify", "me"
        )

        assert result.exit_code == 1
        assert message in result.output


class TestGchatWatchCommands:
    def test_arm_passes_every_option(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_arm(**kwargs: Any) -> Result[Watch]:
            captured.update(kwargs)
            return ok(WATCH)

        monkeypatch.setattr(gchat_watch, "arm_watch", fake_arm)

        result = invoke(
            runner,
            "gchat-watch",
            "arm",
            "--space",
            "S",
            "--thread",
            "T",
            "--notify",
            "me",
            "--notify-role",
            "tt-backend",
            "--route",
            "--mode",
            "ttl",
            "--ttl-hours",
            "2",
        )

        assert result.exit_code == 0, result.output
        assert captured == {
            "space": "S",
            "thread": "T",
            "notify": ("me",),
            "notify_roles": ("tt-backend",),
            "route": True,
            "mode": "ttl",
            "ttl": timedelta(hours=2),
        }
        assert ARMED_LINE in result.output

    def test_disarm_prints_the_removed_id(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gchat_watch, "disarm_watch", lambda **_: ok(WATCH))

        result = invoke(runner, "gchat-watch", "disarm", "--id", "S.T")

        assert result.output == "DISARMED S.T\n"

    def test_list_prints_one_line_per_watch(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        space_watch = Watch(
            id="Z",
            space="spaces/Z",
            thread=None,
            notify=(),
            notify_roles=(),
            route=True,
            mode="ttl",
            armed_at=ARMED,
            expires_at=ARMED,
        )
        monkeypatch.setattr(gchat_watch, "list_watches", lambda **_: ok([WATCH, space_watch]))

        result = invoke(runner, "gchat-watch", "list")

        assert result.output.splitlines() == [
            ARMED_LINE.replace("ARMED", "WATCH"),
            "WATCH Z spaces/Z mode=ttl notify=- route=yes expires=2026-10-30T12:00:00+00:00",
        ]

    def test_list_says_when_nothing_is_armed(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gchat_watch, "list_watches", lambda **_: ok([]))

        assert invoke(runner, "gchat-watch", "list").output == "No armed Google Chat watches.\n"

    @pytest.mark.parametrize(
        ("command", "function"),
        [
            (["arm", "--space", "S", "--notify", "me"], "arm_watch"),
            (["disarm", "--id", "S.T"], "disarm_watch"),
            (["list"], "list_watches"),
        ],
    )
    def test_errors_exit_nonzero(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        command: list[str],
        function: str,
    ) -> None:
        monkeypatch.setattr(gchat_watch, function, lambda **_: err("store locked"))

        result = invoke(runner, "gchat-watch", *command)

        assert result.exit_code == 1
        assert "ERROR store locked" in result.output


class TestGchatWatchPoll:
    @pytest.fixture
    def polled(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        captured: dict[str, Any] = {"calls": 0, "slept": []}
        reports = [
            ok(PollReport(events=(), armed=1)),
            ok(PollReport(events=(WatchEvent(kind="NEW", parts=("m", "u", "t")),), armed=1)),
        ]

        def fake_poll(**kwargs: Any) -> Result[PollReport]:
            captured["kwargs"] = kwargs
            captured["calls"] += 1
            return reports.pop(0)

        monkeypatch.setattr(gchat_watch, "poll_once", fake_poll)
        monkeypatch.setattr("time.sleep", captured["slept"].append)
        return captured

    def test_once_exits_after_the_first_batch_with_events(
        self, runner: CliRunner, polled: dict[str, Any]
    ) -> None:
        result = invoke(runner, "gchat-watch", "poll", "--once", "--interval", "3")

        assert result.exit_code == 0, result.output
        assert result.output == "NEW m u t\n"
        assert polled["calls"] == 2
        assert polled["slept"] == [3.0]
        assert polled["kwargs"]["reader"] is gchat_watch.gog_reader

    def test_polls_bounds_the_run(self, runner: CliRunner, polled: dict[str, Any]) -> None:
        result = invoke(runner, "gchat-watch", "poll", "--polls", "1")

        assert result.exit_code == 0
        assert polled["calls"] == 1

    def test_a_poll_error_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gchat_watch, "poll_once", lambda **_: err("gog is not installed"))

        result = invoke(runner, "gchat-watch", "poll", "--once")

        assert result.exit_code == 1
        assert "ERROR gog is not installed" in result.output
