"""Tests for the AskUserQuestion → supervisor hook (GH-1692)."""

from __future__ import annotations

import http.client
import io
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

from dev10x.comm.hooks.supervisor_decision import supervisor_decision
from dev10x.comm.supervisor import paths
from dev10x.comm.supervisor.settings import ANSWER_WAIT_MAX

QUESTIONS = [{"question": "Which hub?", "header": "Hub", "options": [{"label": "Relay"}]}]
PAYLOAD = {
    "session_id": "sid-1",
    "cwd": "/w",
    "tool_name": "AskUserQuestion",
    "tool_input": {"questions": QUESTIONS},
}


class FakeOpener:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        replies: list[dict[str, Any]] | None = None,
    ) -> None:
        self.requests: list[tuple[urllib.request.Request, float]] = []
        self.error = error
        self.replies = list(replies or [])

    def __call__(self, request: urllib.request.Request, *, timeout: float) -> io.BytesIO:
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        reply = self.replies.pop(0) if self.replies else {}
        return io.BytesIO(json.dumps(reply).encode())

    @property
    def paths(self) -> list[str]:
        return [
            request.full_url.removeprefix("http://127.0.0.1:8765") for request, _ in self.requests
        ]


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "config"))
    monkeypatch.delenv(paths.PORT_ENV_VAR, raising=False)
    Dev10xConfigDir.reset_cache()
    yield tmp_path / "config"
    Dev10xConfigDir.reset_cache()


@pytest.fixture
def token(config_home: Path) -> str:
    paths.token_path().parent.mkdir(parents=True)
    paths.token_path().write_text("tok-1\n", encoding="utf-8")
    return "tok-1"


class TestPosts:
    @pytest.fixture
    def sent(self, token: str) -> tuple[urllib.request.Request, float]:
        opener = FakeOpener()
        supervisor_decision(PAYLOAD, opener=opener, in_herdr=lambda: True)
        [request] = opener.requests
        return request

    def test_url_and_token(self, sent: tuple[urllib.request.Request, float]) -> None:
        request, timeout = sent

        assert (request.full_url, request.get_header("X-supervisor-token"), timeout) == (
            "http://127.0.0.1:8765/decisions",
            "tok-1",
            1.0,
        )

    def test_body(self, sent: tuple[urllib.request.Request, float]) -> None:
        request, _ = sent

        assert json.loads(request.data) == {  # type: ignore[arg-type]
            "session_id": "sid-1",
            "cwd": "/w",
            "questions": QUESTIONS,
            "hold": False,
        }

    @pytest.mark.parametrize(("env", "held"), [("1", False), ("", True)])
    def test_holds_only_outside_herdr(
        self,
        token: str,
        monkeypatch: pytest.MonkeyPatch,
        env: str,
        held: bool,
    ) -> None:
        monkeypatch.setenv("HERDR_ENV", env)
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener)

        assert json.loads(opener.requests[0][0].data)["hold"] is held  # type: ignore[arg-type]

    @pytest.mark.parametrize(("env", "port"), [("9100", 9100), ("junk", 8765)])
    def test_port_from_env(
        self,
        token: str,
        monkeypatch: pytest.MonkeyPatch,
        env: str,
        port: int,
    ) -> None:
        monkeypatch.setenv(paths.PORT_ENV_VAR, env)
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener)

        assert opener.requests[0][0].full_url == f"http://127.0.0.1:{port}/decisions"


class TestWaitsForThePage:
    @pytest.fixture
    def time(self) -> FakeTime:
        return FakeTime()

    def _run(
        self, *, replies: list[dict[str, Any]], time: FakeTime
    ) -> tuple[FakeOpener, list[str]]:
        opener = FakeOpener(replies=replies)
        emitted: list[str] = []
        supervisor_decision(
            PAYLOAD,
            opener=opener,
            in_herdr=lambda: False,
            clock=time.clock,
            sleep=time.sleep,
            emit=emitted.append,
        )
        return opener, emitted

    def test_answers_the_question_once_the_page_does(self, token: str, time: FakeTime) -> None:
        opener, emitted = self._run(
            replies=[
                {"decision_ids": ["d1"], "wait_seconds": 30},
                {"ok": True, "answers": None},
                {"ok": True, "answers": {"Which hub?": "Relay"}},
            ],
            time=time,
        )

        assert (opener.paths, [json.loads(line) for line in emitted]) == (
            ["/decisions", "/decisions/answers", "/decisions/answers"],
            [
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": "Answered on the supervisor page.",
                        "updatedInput": {
                            "questions": QUESTIONS,
                            "answers": {"Which hub?": "Relay"},
                        },
                    }
                }
            ],
        )

    def test_hands_the_question_back_when_the_wait_ends(self, token: str, time: FakeTime) -> None:
        opener, emitted = self._run(
            replies=[{"decision_ids": ["d1"], "wait_seconds": 2}], time=time
        )

        assert (opener.paths, emitted, json.loads(opener.requests[-1][0].data)) == (  # type: ignore[arg-type]
            ["/decisions", "/decisions/answers", "/decisions/answers", "/decisions/release"],
            [],
            {"decision_ids": ["d1"]},
        )

    @pytest.mark.parametrize(
        "reply",
        [
            {"decision_ids": ["d1"], "wait_seconds": 0},
            {"decision_ids": ["d1"]},
            {"decision_ids": [], "wait_seconds": 30},
            {"decision_ids": ["d1"], "wait_seconds": "soon"},
        ],
        ids=["no-wait", "old-daemon", "nothing-stored", "bad-wait"],
    )
    def test_steps_aside_without_a_wait(
        self, token: str, time: FakeTime, reply: dict[str, Any]
    ) -> None:
        opener, emitted = self._run(replies=[reply], time=time)

        assert (opener.paths, emitted) == (["/decisions"], [])


class TestDevFanOut:
    @pytest.fixture
    def dev_token(self, config_home: Path) -> str:
        path = paths.token_path(instance=paths.Instance.DEV)
        path.parent.mkdir(parents=True)
        path.write_text("dev-tok\n", encoding="utf-8")
        return "dev-tok"

    @pytest.fixture
    def pinned(self, config_home: Path, tmp_path: Path) -> None:
        checkout = tmp_path / "Dev10x-Claude"
        checkout.mkdir()
        (checkout / "pyproject.toml").write_text('[project]\nname = "Dev10x"\n', encoding="utf-8")
        config_home.mkdir(parents=True, exist_ok=True)
        (config_home / "overwatch.yaml").write_text(
            f"dev:\n  checkout: {checkout}\n  port: 9300\n", encoding="utf-8"
        )

    def test_mirrors_to_dev_before_release(self, token: str, dev_token: str, pinned: None) -> None:
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener, in_herdr=lambda: True)

        assert [
            (request.full_url, request.get_header("X-supervisor-token"))
            for request, _ in opener.requests
        ] == [
            ("http://127.0.0.1:9300/decisions", "dev-tok"),
            ("http://127.0.0.1:8765/decisions", "tok-1"),
        ]

    def test_dev_copy_never_holds_the_session(
        self, token: str, dev_token: str, pinned: None
    ) -> None:
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener, in_herdr=lambda: False)

        assert [
            json.loads(request.data)["hold"]  # type: ignore[arg-type]
            for request, _ in opener.requests
        ] == [False, True]

    def test_dev_still_gets_it_when_release_is_down(
        self, config_home: Path, dev_token: str, pinned: None
    ) -> None:
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener, in_herdr=lambda: True)

        assert [request.full_url for request, _ in opener.requests] == [
            "http://127.0.0.1:9300/decisions"
        ]

    def test_pinned_without_a_dev_token_posts_release_only(self, token: str, pinned: None) -> None:
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener, in_herdr=lambda: True)

        assert [request.full_url for request, _ in opener.requests] == [
            "http://127.0.0.1:8765/decisions"
        ]

    def test_no_pin_means_release_only(self, token: str, dev_token: str) -> None:
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener, in_herdr=lambda: True)

        assert len(opener.requests) == 1


class TestSilence:
    @pytest.mark.parametrize(
        "error",
        [
            urllib.error.URLError("refused"),
            TimeoutError("slow"),
            ValueError("bad"),
            http.client.BadStatusLine("garbage"),
        ],
        ids=["refused", "timeout", "value", "not-http"],
    )
    def test_silent_when_daemon_down(
        self,
        token: str,
        capsys: pytest.CaptureFixture[str],
        error: Exception,
    ) -> None:
        result = supervisor_decision(PAYLOAD, opener=FakeOpener(error=error))

        assert (result, capsys.readouterr()) == (None, ("", ""))

    def test_silent_without_token_file(self, config_home: Path) -> None:
        opener = FakeOpener()

        supervisor_decision(PAYLOAD, opener=opener)

        assert opener.requests == []

    @pytest.mark.parametrize(
        "payload",
        [
            {**PAYLOAD, "tool_input": {}},
            {**PAYLOAD, "tool_input": {"questions": []}},
            {**PAYLOAD, "session_id": ""},
            {"session_id": "sid-1"},
            {"session_id": "sid-1", "tool_input": ["questions"]},
            ["not", "a", "dict"],
        ],
        ids=[
            "no-questions",
            "empty-questions",
            "no-session",
            "no-tool-input",
            "tool-input-not-dict",
            "payload-not-dict",
        ],
    )
    def test_ignores_payload_without_questions(self, token: str, payload: Any) -> None:
        opener = FakeOpener()

        supervisor_decision(payload, opener=opener)

        assert opener.requests == []

    def test_reads_stdin_when_no_data(
        self,
        token: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(PAYLOAD)))
        opener = FakeOpener()

        supervisor_decision(opener=opener)

        assert len(opener.requests) == 1


def test_comm_hooks_register_ask_user_question() -> None:
    hooks = json.loads((Path(__file__).parents[2] / "hooks" / "hooks.d" / "comm.json").read_text())
    [entry] = [e for e in hooks["hooks"]["PreToolUse"] if e["matcher"] == "AskUserQuestion"]
    [hook] = entry["hooks"]

    assert (
        hook["command"].split()[0],
        hook["command"].endswith("supervisor-decision.py"),
        hook["timeout"] > ANSWER_WAIT_MAX,
    ) == ("$CLAUDE_PLUGIN_ROOT/hooks/scripts/audit-wrap", True, True)
