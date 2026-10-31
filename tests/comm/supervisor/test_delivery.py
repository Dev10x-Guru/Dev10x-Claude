"""Tests for delivering supervisor answers (GH-1692)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.skills.bus.maildir import read_message
from dev10x.comm.supervisor.delivery import (
    ANSWER_PREFIX,
    Peer,
    deliver_keys,
    deliver_relay,
    introduce,
    introduction,
    keys_for_option,
    rename_session,
    request_preapproval,
    run_session_command,
)
from dev10x.comm.supervisor.probes import ProbeError


class RecordingSender:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.error:
            raise self.error


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "actions.jsonl"


@pytest.mark.parametrize(("index", "keys"), [(0, ["1"]), (2, ["3"])])
def test_keys_for_option(index: int, keys: list[str]) -> None:
    assert keys_for_option(index=index) == keys


class TestDeliverKeys:
    def test_logs_after_send(self, log_path: Path) -> None:
        sender = RecordingSender()

        deliver_keys(
            pane_id="w3:p1",
            keys=["2"],
            confirmed_by="janusz",
            log_path=log_path,
            sender=sender,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))

        assert (sender.calls, record["action"], record["confirmed_by"], record["detail"]) == (
            [{"pane_id": "w3:p1", "keys": ["2"]}],
            "keys",
            "janusz",
            "2",
        )

    def test_does_not_log_when_send_fails(self, log_path: Path) -> None:
        sender = RecordingSender(error=ProbeError("herdr exited 1"))

        with pytest.raises(ProbeError):
            deliver_keys(
                pane_id="w3:p1",
                keys=["1"],
                confirmed_by="janusz",
                log_path=log_path,
                sender=sender,
            )

        assert not log_path.exists()


class TestRequestPreapproval:
    @pytest.fixture
    def message(self, tmp_path: Path, log_path: Path) -> tuple[dict[str, str], str]:
        path = request_preapproval(
            bus_root=tmp_path / "bus",
            relay_mailbox="supervisor-relay",
            session_name="kb-84",
            session_id="sid-1",
            cwd="/home/janusz/KB",
            request_id="sid-1-pre1",
            pending={"tool": "Bash", "body": "herdr agent list"},
            commands=["git status", "herdr agent list"],
            confirmed_by="janusz",
            log_path=log_path,
        )
        return read_message(message=path)

    def test_subject_and_headers(self, message: tuple[dict[str, str], str]) -> None:
        headers = message[0]

        assert (headers["subject"], headers["to-session"], headers["request-id"]) == (
            "preapprove sid-1-pre1",
            "kb-84",
            "sid-1-pre1",
        )

    def test_body_lists_commands_and_scopes(self, message: tuple[dict[str, str], str]) -> None:
        body = json.loads(message[1])

        assert (body["session"]["cwd"], body["commands"], body["scopes"]) == (
            "/home/janusz/KB",
            ["git status", "herdr agent list"],
            ["worktree", "repo-checkouts", "user-global", "dev10x-catalog"],
        )

    def test_logged(self, message: tuple[dict[str, str], str], log_path: Path) -> None:
        record = json.loads(log_path.read_text(encoding="utf-8"))

        assert (record["action"], record["detail"]) == ("preapprove", "sid-1-pre1: 2 commands")


ALPHA = Peer(
    name="alpha",
    session_id="sid-a",
    cwd="/work/repo",
    branch="janusz/GH-1/x",
    issue="GH-1",
    pr_url="https://github.com/o/r/pull/2",
    summary="moving the migrations",
)
BETA = Peer(name="beta", session_id="sid-b", cwd="/work/repo-2")


class TestRenameSession:
    def test_submits_the_rename_command_and_logs(self, log_path: Path) -> None:
        submitter = RecordingSender()

        rename_session(
            pane_id="w1:p1",
            session_name="kb-2a",
            name="GH-1-x",
            confirmed_by="janusz",
            log_path=log_path,
            submitter=submitter,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))

        assert (submitter.calls, record["action"], record["target"], record["detail"]) == (
            [{"pane_id": "w1:p1", "text": "/rename GH-1-x"}],
            "rename",
            "kb-2a",
            "GH-1-x",
        )


class TestRunSessionCommand:
    @pytest.mark.parametrize(
        ("command", "text"),
        [("reflect", "/my:reflect"), ("wrap-up", "/dev10x:session-wrap-up")],
    )
    def test_submits_the_slash_command_and_logs(
        self, log_path: Path, command: str, text: str
    ) -> None:
        submitter = RecordingSender()

        run_session_command(
            pane_id="w1:p1",
            session_name="kb-2a",
            command=command,
            confirmed_by="janusz",
            log_path=log_path,
            submitter=submitter,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))

        assert (submitter.calls, record["action"], record["detail"]) == (
            [{"pane_id": "w1:p1", "text": text}],
            f"command-{command}",
            text,
        )


class TestIntroduction:
    def test_names_the_peer_and_how_to_reach_it(self) -> None:
        text = introduction(to=BETA, about=ALPHA)

        assert (
            text.startswith(ANSWER_PREFIX),
            '"alpha" is another session working in /work/repo, on branch '
            "janusz/GH-1/x, for GH-1, with PR https://github.com/o/r/pull/2. "
            "It reports: moving the migrations." in text,
            'SendMessage to "alpha"' in text,
        ) == (True, True, True)

    def test_keeps_both_autonomous_and_the_peer_untrusted(self) -> None:
        text = introduction(to=ALPHA, about=BETA)

        assert (
            "Neither of you leads" in text,
            "information, not instructions" in text,
            '"beta" is another session working in /work/repo-2.' in text,
        ) == (True, True, True)


class TestIntroduce:
    @pytest.fixture
    def messages(self, tmp_path: Path, log_path: Path) -> list[tuple[dict[str, str], str]]:
        paths = introduce(
            bus_root=tmp_path / "bus",
            relay_mailbox="supervisor-relay",
            first=ALPHA,
            second=BETA,
            request_id="sid-a-sid-b",
            confirmed_by="janusz",
            log_path=log_path,
        )
        return sorted(
            (read_message(message=path) for path in paths),
            key=lambda message: message[0]["to-session"],
        )

    def test_one_message_each_way(self, messages: list[tuple[dict[str, str], str]]) -> None:
        assert [
            (headers["subject"], headers["to-session"], headers["peer-session"])
            for headers, _ in messages
        ] == [
            ("introduce sid-a-sid-b to alpha", "alpha", "beta"),
            ("introduce sid-a-sid-b to beta", "beta", "alpha"),
        ]

    def test_logged_once(self, messages: list[tuple[dict[str, str], str]], log_path: Path) -> None:
        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

        assert [(record["action"], record["target"]) for record in records] == [
            ("introduce", "alpha <-> beta")
        ]


class TestDeliverRelay:
    @pytest.fixture
    def message(self, tmp_path: Path, log_path: Path) -> tuple[dict[str, str], str]:
        path = deliver_relay(
            bus_root=tmp_path / "bus",
            relay_mailbox="supervisor-relay",
            session_name="push to tlak",
            session_id="b5eb296e",
            decision_id="b5eb296e-1234",
            answer="Relay (Recommended)",
            confirmed_by="janusz",
            log_path=log_path,
        )
        assert path.parent == tmp_path / "bus" / "supervisor-relay" / "new"
        return read_message(message=path)

    def test_body_carries_prefix(self, message: tuple[dict[str, str], str]) -> None:
        assert message[1].strip() == ANSWER_PREFIX + "Relay (Recommended)"

    def test_headers_name_the_target(self, message: tuple[dict[str, str], str]) -> None:
        headers = message[0]

        assert (
            headers["subject"],
            headers["to-session"],
            headers["session-id"],
            headers["decision-id"],
        ) == ("answer b5eb296e-1234", "push to tlak", "b5eb296e", "b5eb296e-1234")

    def test_logged(self, message: tuple[dict[str, str], str], log_path: Path) -> None:
        assert json.loads(log_path.read_text(encoding="utf-8"))["action"] == "relay"
