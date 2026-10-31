"""Tests for the supervisor HTTP server and collector (GH-1692)."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from dev10x.comm.skills.bus.maildir import mailbox_unread, read_message
from dev10x.comm.supervisor.decisions import ANSWERED, DELIVERED, OPEN, DecisionStore
from dev10x.comm.supervisor.paths import TOKEN_HEADER
from dev10x.comm.supervisor.probes import ProbeError, Snapshot
from dev10x.comm.supervisor.server import (
    MAX_BODY_BYTES,
    SupervisorApp,
    make_server,
    refresh,
    run_collector,
)
from dev10x.comm.supervisor.sessions import SessionView
from tests.comm.supervisor.conftest import NOW

TOKEN = "tok-123"
RELAY = "supervisor-relay"
WAITING = SessionView(
    session_id="sid-wait",
    name="kb-84",
    cwd="/kb",
    status="waiting",
    waiting_for="input needed",
    pane_id="w3:p1",
    callsign="",
    summary="",
    board_state="",
    group="needs-you",
)
IDLE = replace(
    WAITING,
    session_id="sid-idle",
    name="mc-updates",
    status="idle",
    waiting_for="",
    pane_id="w12:p1",
    group="done",
)
PERMISSION = replace(WAITING, session_id="sid-perm", name="perms", waiting_for="permission prompt")
QUESTION = {
    "question": "Which hub?",
    "header": "Hub",
    "options": [{"label": "Relay"}, {"label": "mc"}],
}


class KeySender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.error:
            raise self.error


@dataclass
class Response:
    status: int
    body: str
    headers: dict[str, str]

    def json(self) -> Any:
        return json.loads(self.body)


@pytest.fixture
def keys() -> KeySender:
    return KeySender()


@pytest.fixture
def app(tmp_path: Path, keys: KeySender) -> SupervisorApp:
    return SupervisorApp(
        store=DecisionStore(path=tmp_path / "decisions.json"),
        bus_root=tmp_path / "bus",
        kb_root=tmp_path / "kb",
        log_path=tmp_path / "actions.jsonl",
        token=TOKEN,
        relay_mailbox=RELAY,
        key_sender=keys,
        pane_reader=lambda pane_id: f"pane {pane_id}",
        today=lambda: date(2026, 10, 31),
        snapshot=Snapshot(sessions=[WAITING, IDLE, PERMISSION], taken_at=NOW),
    )


@pytest.fixture
def port(app: SupervisorApp) -> Iterator[int]:
    server = make_server(app=app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def call(
    *,
    port: int,
    method: str,
    path: str,
    form: dict[str, str] | None = None,
    payload: Any = None,
    token: str | None = TOKEN,
    raw: bytes | None = None,
) -> Response:
    headers: dict[str, str] = {}
    body = raw
    if token is not None:
        headers[TOKEN_HEADER] = token
    if form is not None:
        body = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return Response(
            status=response.status,
            body=response.read().decode(),
            headers=dict(response.getheaders()),
        )
    finally:
        connection.close()


def add_decision(*, app: SupervisorApp, session_id: str) -> str:
    [decision] = app.store.add_from_hook(session_id=session_id, cwd="/w", questions=[QUESTION])
    return decision.decision_id


class TestAuth:
    @pytest.mark.parametrize("path", ["/", "/api/sessions", "/lessons"])
    def test_get_requires_token(self, port: int, path: str) -> None:
        assert call(port=port, method="GET", path=path, token=None).status == 403

    @pytest.mark.parametrize("path", ["/decisions", "/answer", "/keys", "/reply", "/lessons"])
    def test_post_without_token_forbidden(self, port: int, path: str) -> None:
        assert call(port=port, method="POST", path=path, form={}, token=None).status == 403

    def test_wrong_token_forbidden(self, port: int) -> None:
        assert call(port=port, method="GET", path="/", token="nope").status == 403

    def test_token_in_query(self, port: int) -> None:
        assert call(port=port, method="GET", path=f"/?token={TOKEN}", token=None).status == 200

    def test_unknown_route(self, port: int) -> None:
        assert call(port=port, method="GET", path="/nope").status == 404


class TestPageAndApi:
    def test_page_lists_sessions(self, port: int) -> None:
        response = call(port=port, method="GET", path="/")

        assert (response.status, "kb-84" in response.body) == (200, True)

    def test_api_returns_snapshot(self, port: int, app: SupervisorApp) -> None:
        add_decision(app=app, session_id=WAITING.session_id)

        payload = call(port=port, method="GET", path="/api/sessions").json()

        assert ([s["name"] for s in payload["sessions"]], len(payload["decisions"])) == (
            ["kb-84", "mc-updates", "perms"],
            1,
        )


class TestDecisions:
    def test_post_decisions_then_page_lists_options(self, port: int) -> None:
        created = call(
            port=port,
            method="POST",
            path="/decisions",
            payload={"session_id": WAITING.session_id, "cwd": "/kb", "questions": [QUESTION]},
        )
        page = call(port=port, method="GET", path="/")

        assert (
            created.status,
            len(created.json()["decision_ids"]),
            ">mc</button>" in page.body,
        ) == (
            201,
            1,
            True,
        )

    @pytest.mark.parametrize(
        "payload",
        [{"questions": []}, {"session_id": "x", "questions": "nope"}],
        ids=["no-session", "questions-not-list"],
    )
    def test_post_decisions_validates(self, port: int, payload: dict[str, Any]) -> None:
        assert call(port=port, method="POST", path="/decisions", payload=payload).status == 400

    def test_post_decisions_needs_json(self, port: int) -> None:
        assert call(port=port, method="POST", path="/decisions", form={"a": "b"}).status == 400

    @pytest.mark.parametrize(
        ("raw", "status"),
        [(b"{bad", 400), (b"[1]", 400)],
        ids=["bad-json", "not-object"],
    )
    def test_post_bad_json(self, port: int, raw: bytes, status: int) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "POST",
            "/decisions",
            body=raw,
            headers={TOKEN_HEADER: TOKEN, "Content-Type": "application/json"},
        )

        assert connection.getresponse().status == status

    def test_body_too_large(self, port: int) -> None:
        response = call(
            port=port,
            method="POST",
            path="/decisions",
            raw=b"x" * (MAX_BODY_BYTES + 1),
        )

        assert response.status == 413


class TestAnswer:
    def test_waiting_session_sends_keys(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
    ) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            form={"decision_id": decision_id, "option_index": "1"},
        )
        stored = app.store.get(decision_id=decision_id)

        assert (
            response.status,
            response.headers["Location"],
            keys.calls,
            stored and (stored.state, stored.answer, stored.channel),
        ) == (
            303,
            f"/?token={TOKEN}",
            [{"pane_id": "w3:p1", "keys": ["2"]}],
            (ANSWERED, "mc", "keys"),
        )

    def test_idle_session_relays(self, port: int, app: SupervisorApp, keys: KeySender) -> None:
        decision_id = add_decision(app=app, session_id=IDLE.session_id)

        call(
            port=port,
            method="POST",
            path="/answer",
            form={"decision_id": decision_id, "option_index": "0"},
        )
        [message] = mailbox_unread(root=app.bus_root, name=RELAY)
        headers, body = read_message(message=message)

        assert (keys.calls, headers["to-session"], body.strip()) == (
            [],
            "mc-updates",
            "Answer from Janusz: Relay",
        )

    def test_vanished_session_conflicts(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
    ) -> None:
        decision_id = add_decision(app=app, session_id="gone")

        response = call(
            port=port,
            method="POST",
            path="/answer",
            form={"decision_id": decision_id, "option_index": "0"},
        )

        assert (response.status, keys.calls, (app.bus_root / RELAY).exists()) == (
            409,
            [],
            False,
        )

    def test_answer_twice_conflicts(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
    ) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)
        form = {"decision_id": decision_id, "option_index": "0"}

        call(port=port, method="POST", path="/answer", form=form)
        second = call(port=port, method="POST", path="/answer", form=form)

        assert (second.status, len(keys.calls)) == (409, 1)

    @pytest.mark.parametrize("option_index", ["x", "5", "-1"])
    def test_bad_option_index(self, port: int, app: SupervisorApp, option_index: str) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            form={"decision_id": decision_id, "option_index": option_index},
        )

        assert response.status == 400

    def test_failed_keys_reopen_decision(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
    ) -> None:
        keys.error = ProbeError("herdr exited 1")
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            form={"decision_id": decision_id, "option_index": "0"},
        )
        stored = app.store.get(decision_id=decision_id)

        assert (response.status, stored and stored.state) == (502, OPEN)

    def test_lost_race_conflicts(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)
        monkeypatch.setattr(app.store, "answer", lambda **_: None)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            form={"decision_id": decision_id, "option_index": "0"},
        )

        assert (response.status, keys.calls) == (409, [])

    def test_lost_race_on_relay_conflicts(
        self,
        port: int,
        app: SupervisorApp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        decision_id = add_decision(app=app, session_id=IDLE.session_id)
        monkeypatch.setattr(app.store, "answer", lambda **_: None)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            form={"decision_id": decision_id, "option_index": "0"},
        )

        assert (response.status, (app.bus_root / RELAY).exists()) == (409, False)


class TestKeysAndReply:
    @pytest.mark.parametrize(("allow", "sent"), [("1", ["1"]), ("0", ["esc"])])
    def test_permission_keys(
        self,
        port: int,
        keys: KeySender,
        allow: str,
        sent: list[str],
    ) -> None:
        response = call(
            port=port,
            method="POST",
            path="/keys",
            form={"session_id": PERMISSION.session_id, "allow": allow},
        )

        assert (response.status, keys.calls) == (303, [{"pane_id": "w3:p1", "keys": sent}])

    def test_keys_refused_off_prompt(self, port: int, keys: KeySender) -> None:
        response = call(
            port=port,
            method="POST",
            path="/keys",
            form={"session_id": WAITING.session_id, "allow": "1"},
        )

        assert (response.status, keys.calls) == (409, [])

    def test_keys_failure_reported(self, port: int, keys: KeySender) -> None:
        keys.error = ProbeError("herdr exited 1")

        response = call(
            port=port,
            method="POST",
            path="/keys",
            form={"session_id": PERMISSION.session_id, "allow": "1"},
        )

        assert (response.status, "herdr exited 1" in response.body) == (502, True)

    def test_reply_relays_text(self, port: int, app: SupervisorApp) -> None:
        response = call(
            port=port,
            method="POST",
            path="/reply",
            form={"session_id": IDLE.session_id, "text": " Go with B "},
        )
        [message] = mailbox_unread(root=app.bus_root, name=RELAY)

        assert (response.status, read_message(message=message)[1].strip()) == (
            303,
            "Answer from Janusz: Go with B",
        )

    def test_reply_empty_rejected(self, port: int) -> None:
        response = call(
            port=port,
            method="POST",
            path="/reply",
            form={"session_id": IDLE.session_id, "text": "  "},
        )

        assert response.status == 400

    def test_reply_unknown_session_conflicts(self, port: int) -> None:
        response = call(
            port=port, method="POST", path="/reply", form={"session_id": "gone", "text": "hi"}
        )

        assert response.status == 409


class TestLessons:
    LESSON = {
        "title": "Hooks load once",
        "body": "Restart after an upgrade.",
        "repo": "dev10x-claude",
        "topic": "hooks",
        "tags": ["claude-code"],
        "source_session": "47a1ef74",
    }

    def test_roundtrip(self, port: int) -> None:
        created = call(port=port, method="POST", path="/lessons", payload=self.LESSON)
        found = call(port=port, method="GET", path="/lessons?repo=dev10x-claude&q=upgrade")

        assert (created.status, [item["title"] for item in found.json()["lessons"]]) == (
            201,
            ["Hooks load once"],
        )

    def test_scalar_tag_accepted(self, port: int) -> None:
        payload = {**self.LESSON, "tags": "solo"}

        call(port=port, method="POST", path="/lessons", payload=payload)
        [lesson] = call(port=port, method="GET", path="/lessons").json()["lessons"]

        assert lesson["tags"] == ["solo"]

    def test_missing_fields(self, port: int) -> None:
        response = call(port=port, method="POST", path="/lessons", payload={"title": "x"})

        assert (response.status, "body, repo, topic" in response.body) == (400, True)


class TestCollector:
    def test_refresh_reads_pane_for_needs_you(self, app: SupervisorApp) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[WAITING, IDLE], taken_at=NOW))

        assert app.pane_text == {"sid-wait": "pane w3:p1"}

    def test_keys_answer_delivered_when_session_moves_on(self, app: SupervisorApp) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)
        app.store.answer(decision_id=decision_id, answer="Relay", channel="keys")

        refresh(
            app=app,
            provider=lambda: Snapshot(sessions=[replace(WAITING, status="busy")], taken_at=NOW),
        )

        assert app.store.get(decision_id=decision_id).state == DELIVERED  # type: ignore[union-attr]

    @pytest.mark.parametrize(("status", "state"), [("idle", ANSWERED), ("busy", DELIVERED)])
    def test_relay_answer_delivered_once_session_works(
        self,
        app: SupervisorApp,
        status: str,
        state: str,
    ) -> None:
        decision_id = add_decision(app=app, session_id=IDLE.session_id)
        app.store.answer(decision_id=decision_id, answer="Relay", channel="relay")

        refresh(
            app=app,
            provider=lambda: Snapshot(sessions=[replace(IDLE, status=status)], taken_at=NOW),
        )

        assert app.store.get(decision_id=decision_id).state == state  # type: ignore[union-attr]

    def test_open_decision_expires_when_answered_in_terminal(self, app: SupervisorApp) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        refresh(
            app=app,
            provider=lambda: Snapshot(sessions=[replace(WAITING, status="busy")], taken_at=NOW),
        )

        assert app.store.get(decision_id=decision_id).state == DELIVERED  # type: ignore[union-attr]

    def test_open_decision_kept_before_widget_shows(self, app: SupervisorApp) -> None:
        busy = replace(WAITING, status="busy")
        app.snapshot = Snapshot(sessions=[busy], taken_at=NOW)
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        refresh(app=app, provider=lambda: Snapshot(sessions=[busy], taken_at=NOW))

        assert app.store.get(decision_id=decision_id).state == OPEN  # type: ignore[union-attr]

    def test_run_collector_survives_a_failed_tick(self, app: SupervisorApp) -> None:
        stop = threading.Event()
        ticks: list[int] = []

        def provider() -> Snapshot:
            ticks.append(1)
            if len(ticks) == 1:
                raise RuntimeError("probe blew up")
            stop.set()
            return Snapshot(sessions=[IDLE], taken_at=NOW)

        run_collector(app=app, interval=0, stop=stop, provider=provider)

        assert (len(ticks), [view.name for view in app.snapshot.sessions]) == (2, ["mc-updates"])
