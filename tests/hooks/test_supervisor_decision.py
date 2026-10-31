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

QUESTIONS = [{"question": "Which hub?", "header": "Hub", "options": [{"label": "Relay"}]}]
PAYLOAD = {
    "session_id": "sid-1",
    "cwd": "/w",
    "tool_name": "AskUserQuestion",
    "tool_input": {"questions": QUESTIONS},
}


class FakeOpener:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.requests: list[tuple[urllib.request.Request, float]] = []
        self.error = error

    def __call__(self, request: urllib.request.Request, *, timeout: float) -> io.BytesIO:
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(b"{}")


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
        supervisor_decision(PAYLOAD, opener=opener)
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
        }

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

    assert (hook["command"].split()[0], hook["command"].endswith("supervisor-decision.py")) == (
        "$CLAUDE_PLUGIN_ROOT/hooks/scripts/audit-wrap",
        True,
    )
