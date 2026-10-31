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

import pytest

from dev10x.comm.skills.bus.maildir import mailbox_unread, read_message
from dev10x.comm.supervisor import server as server_module
from dev10x.comm.supervisor.decisions import ANSWERED, DELIVERED, OPEN, DecisionStore
from dev10x.comm.supervisor.paths import TOKEN_HEADER
from dev10x.comm.supervisor.probes import ProbeError, Snapshot
from dev10x.comm.supervisor.server import (
    MAX_BODY_BYTES,
    SupervisorApp,
    make_server,
    refresh,
    run_collector,
    snapshot_payload,
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
PERMISSION = replace(
    WAITING, session_id="sid-perm", name="perms", waiting_for="permission prompt", pane_id="w5:p1"
)
QUESTION = {
    "question": "Which hub?",
    "header": "Hub",
    "options": [{"label": "Relay"}, {"label": "mc"}],
}
PROMPT_TEXT = " Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, and don't ask again\n   3. No\n"
PANES = {"w3:p1": "working on it\n", "w5:p1": PROMPT_TEXT, "w12:p1": ""}


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
    body: bytes
    headers: dict[str, str]

    def json(self) -> Any:
        return json.loads(self.body)


@pytest.fixture
def keys() -> KeySender:
    return KeySender()


@pytest.fixture
def panes() -> dict[str, str]:
    return dict(PANES)


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Supervisor</title>")
    (root / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    return root


@pytest.fixture
def app(tmp_path: Path, keys: KeySender, panes: dict[str, str], static_dir: Path) -> SupervisorApp:
    supervisor = SupervisorApp(
        store=DecisionStore(path=tmp_path / "decisions.json"),
        bus_root=tmp_path / "bus",
        kb_root=tmp_path / "kb",
        log_path=tmp_path / "actions.jsonl",
        token=TOKEN,
        relay_mailbox=RELAY,
        key_sender=keys,
        pane_reader=lambda pane_id: panes[pane_id],
        today=lambda: date(2026, 10, 31),
        static_dir=static_dir,
    )
    supervisor.publish(
        snapshot=Snapshot(sessions=[WAITING, IDLE, PERMISSION], taken_at=NOW),
        pane_text={"sid-wait": PANES["w3:p1"], "sid-perm": PROMPT_TEXT},
    )
    return supervisor


@pytest.fixture
def port(app: SupervisorApp) -> Iterator[int]:
    server = make_server(app=app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    app.stop()
    server.shutdown()
    server.server_close()


def call(
    *,
    port: int,
    method: str,
    path: str,
    payload: Any = None,
    token: str | None = TOKEN,
    raw: bytes | None = None,
    content_type: str = "application/json",
) -> Response:
    headers: dict[str, str] = {"Content-Type": content_type}
    if token is not None:
        headers[TOKEN_HEADER] = token
    body = raw if payload is None else json.dumps(payload).encode()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return Response(
            status=response.status, body=response.read(), headers=dict(response.getheaders())
        )
    finally:
        connection.close()


def add_decision(*, app: SupervisorApp, session_id: str) -> str:
    [decision] = app.store.add_from_hook(session_id=session_id, cwd="/w", questions=[QUESTION])
    return decision.decision_id


class TestAuth:
    @pytest.mark.parametrize("path", ["/", "/api/sessions", "/api/events", "/lessons"])
    def test_get_requires_token(self, port: int, path: str) -> None:
        assert call(port=port, method="GET", path=path, token=None).status == 403

    @pytest.mark.parametrize("path", ["/decisions", "/answer", "/keys", "/reply", "/lessons"])
    def test_post_without_token_forbidden(self, port: int, path: str) -> None:
        assert call(port=port, method="POST", path=path, payload={}, token=None).status == 403

    def test_wrong_token_forbidden(self, port: int) -> None:
        response = call(port=port, method="GET", path="/", token="nope")

        assert (response.status, response.json()) == (403, {"error": "missing or wrong token"})

    def test_token_in_query(self, port: int) -> None:
        assert call(port=port, method="GET", path=f"/?token={TOKEN}", token=None).status == 200

    def test_unknown_route(self, port: int) -> None:
        assert call(port=port, method="GET", path="/nope").status == 404


class TestStatic:
    def test_page_serves_the_built_index(self, port: int) -> None:
        response = call(port=port, method="GET", path="/")

        assert (response.status, b"<title>Supervisor</title>" in response.body) == (200, True)

    def test_page_without_build(self, port: int, static_dir: Path) -> None:
        (static_dir / "index.html").unlink()

        response = call(port=port, method="GET", path="/")

        assert (response.status, "pnpm build" in response.json()["error"]) == (503, True)

    def test_asset_needs_no_token(self, port: int) -> None:
        response = call(port=port, method="GET", path="/assets/app.js", token=None)

        assert (response.status, response.headers["Content-Type"], response.body) == (
            200,
            "text/javascript",
            b"console.log(1)",
        )

    @pytest.mark.parametrize("path", ["/assets/missing.js", "/assets/../../secret.txt"])
    def test_asset_outside_or_missing(self, port: int, path: str) -> None:
        assert call(port=port, method="GET", path=path, token=None).status == 404


class TestSnapshotPayload:
    @pytest.fixture
    def sessions(self, app: SupervisorApp) -> dict[str, dict[str, Any]]:
        add_decision(app=app, session_id=WAITING.session_id)
        return {item["session_id"]: item for item in snapshot_payload(app=app)["sessions"]}

    def test_prompt_options_parsed_for_waiting_sessions(
        self,
        sessions: dict[str, dict[str, Any]],
    ) -> None:
        assert [
            (option["key"], option["label"])
            for option in sessions["sid-perm"]["prompt"]["options"]
        ] == [("1", "Yes"), ("2", "Yes, and don't ask again"), ("3", "No")]

    def test_no_prompt_without_a_list(self, sessions: dict[str, dict[str, Any]]) -> None:
        assert (sessions["sid-wait"]["prompt"], sessions["sid-idle"]["prompt"]) == (None, None)

    def test_decisions_attached_to_their_session(
        self,
        sessions: dict[str, dict[str, Any]],
    ) -> None:
        assert [len(sessions[sid]["decisions"]) for sid in ("sid-wait", "sid-idle")] == [1, 0]

    def test_excerpt_trims_trailing_blank_lines(self, app: SupervisorApp) -> None:
        app.publish(snapshot=app.snapshot, pane_text={"sid-wait": "a\nb  \n\n\n"})

        [first] = [
            s for s in snapshot_payload(app=app)["sessions"] if s["session_id"] == "sid-wait"
        ]

        assert first["excerpt"] == "a\nb"


class TestApiAndEvents:
    def test_api_returns_snapshot(self, port: int) -> None:
        payload = call(port=port, method="GET", path="/api/sessions").json()

        assert ([s["name"] for s in payload["sessions"]], payload["errors"]) == (
            ["kb-84", "mc-updates", "perms"],
            {},
        )

    def test_events_stream_sends_snapshot_then_updates(
        self,
        port: int,
        app: SupervisorApp,
    ) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", f"/api/events?token={TOKEN}")
        response = connection.getresponse()
        first = response.fp.readline() + response.fp.readline()
        response.fp.readline()
        app.publish(snapshot=Snapshot(sessions=[IDLE], taken_at=NOW), pane_text={})
        response.fp.readline()
        second = json.loads(response.fp.readline().removeprefix(b"data: "))
        app.stop()
        connection.close()

        assert (
            response.headers["Content-Type"],
            first.startswith(b"event: snapshot\ndata: {"),
            [s["name"] for s in second["sessions"]],
        ) == ("text/event-stream", True, ["mc-updates"])

    def test_events_heartbeat(self, port: int, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server_module, "HEARTBEAT_SECONDS", 0.05)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", f"/api/events?token={TOKEN}")
        response = connection.getresponse()
        for _ in range(3):
            response.fp.readline()
        ping = response.fp.readline()
        connection.close()

        assert ping == b": ping\n"

    def test_events_end_on_stop(self, app: SupervisorApp) -> None:
        app.stop()
        handler = _bare_handler(app=app)

        handler._events({})

        assert handler.wfile.getvalue().endswith(b"\r\n\r\n")

    def test_events_survive_a_dropped_client(self, app: SupervisorApp) -> None:
        handler = _bare_handler(app=app, broken=True)

        assert handler._events({}) is None


def _bare_handler(*, app: SupervisorApp, broken: bool = False) -> Any:
    import io

    class Writer(io.BytesIO):
        def write(self, data: bytes) -> int:  # type: ignore[override]
            if broken and data.startswith(b"event:"):
                raise BrokenPipeError
            return super().write(data)

    handler = server_module.SupervisorHandler.__new__(server_module.SupervisorHandler)
    handler.server = type("S", (), {"app": app})()  # type: ignore[assignment]
    handler.wfile = Writer()
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET /api/events HTTP/1.1"
    handler.command = "GET"
    handler.client_address = ("127.0.0.1", 0)
    return handler


class TestDecisions:
    def test_post_decisions_then_snapshot_lists_them(self, port: int) -> None:
        created = call(
            port=port,
            method="POST",
            path="/decisions",
            payload={"session_id": WAITING.session_id, "cwd": "/kb", "questions": [QUESTION]},
        )
        sessions = call(port=port, method="GET", path="/api/sessions").json()["sessions"]

        assert (created.status, sessions[0]["decisions"][0]["options"]) == (201, ["Relay", "mc"])

    @pytest.mark.parametrize(
        "payload",
        [{"questions": []}, {"session_id": "x", "questions": "nope"}],
        ids=["no-session", "questions-not-list"],
    )
    def test_post_decisions_validates(self, port: int, payload: dict[str, Any]) -> None:
        assert call(port=port, method="POST", path="/decisions", payload=payload).status == 400

    def test_post_needs_json(self, port: int) -> None:
        response = call(
            port=port,
            method="POST",
            path="/decisions",
            raw=b"a=b",
            content_type="application/x-www-form-urlencoded",
        )

        assert response.status == 400

    @pytest.mark.parametrize("raw", [b"{bad", b"[1]"], ids=["bad-json", "not-object"])
    def test_post_bad_json(self, port: int, raw: bytes) -> None:
        assert call(port=port, method="POST", path="/decisions", raw=raw).status == 400

    def test_body_too_large(self, port: int) -> None:
        response = call(
            port=port, method="POST", path="/decisions", raw=b"x" * (MAX_BODY_BYTES + 1)
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
            payload={"decision_id": decision_id, "option_index": 1},
        )
        stored = app.store.get(decision_id=decision_id)

        assert (
            response.json(),
            keys.calls,
            stored and (stored.state, stored.answer, stored.channel),
        ) == (
            {"ok": True, "channel": "keys"},
            [{"pane_id": "w3:p1", "keys": ["2"]}],
            (ANSWERED, "mc", "keys"),
        )

    def test_idle_session_relays(self, port: int, app: SupervisorApp, keys: KeySender) -> None:
        decision_id = add_decision(app=app, session_id=IDLE.session_id)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            payload={"decision_id": decision_id, "option_index": 0},
        )
        [message] = mailbox_unread(root=app.bus_root, name=RELAY)
        headers, body = read_message(message=message)

        assert (response.json()["channel"], keys.calls, headers["to-session"], body.strip()) == (
            "relay",
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
            payload={"decision_id": decision_id, "option_index": 0},
        )

        assert (response.status, keys.calls, (app.bus_root / RELAY).exists()) == (409, [], False)

    def test_answer_twice_conflicts(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
    ) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)
        payload = {"decision_id": decision_id, "option_index": 0}

        call(port=port, method="POST", path="/answer", payload=payload)
        second = call(port=port, method="POST", path="/answer", payload=payload)

        assert (second.status, second.json(), len(keys.calls)) == (
            409,
            {"error": "Already answered."},
            1,
        )

    @pytest.mark.parametrize("option_index", ["x", 5, -1, None])
    def test_bad_option_index(self, port: int, app: SupervisorApp, option_index: Any) -> None:
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            payload={"decision_id": decision_id, "option_index": option_index},
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
            payload={"decision_id": decision_id, "option_index": 0},
        )
        stored = app.store.get(decision_id=decision_id)

        assert (response.status, stored and stored.state) == (502, OPEN)

    @pytest.mark.parametrize("session", [WAITING, IDLE], ids=["keys", "relay"])
    def test_lost_race_conflicts(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
        monkeypatch: pytest.MonkeyPatch,
        session: SessionView,
    ) -> None:
        decision_id = add_decision(app=app, session_id=session.session_id)
        monkeypatch.setattr(app.store, "answer", lambda **_: None)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            payload={"decision_id": decision_id, "option_index": 0},
        )

        assert (response.status, keys.calls, (app.bus_root / RELAY).exists()) == (409, [], False)


class TestKeys:
    @pytest.mark.parametrize(("key", "label"), [("1", "Yes"), ("3", "No")])
    def test_sends_a_listed_option(
        self,
        port: int,
        keys: KeySender,
        key: str,
        label: str,
    ) -> None:
        response = call(
            port=port,
            method="POST",
            path="/keys",
            payload={"session_id": PERMISSION.session_id, "key": key, "label": label},
        )

        assert (response.json(), keys.calls) == (
            {"ok": True, "sent": key},
            [{"pane_id": "w5:p1", "keys": [key]}],
        )

    def test_refuses_when_the_prompt_changed(
        self,
        port: int,
        keys: KeySender,
        panes: dict[str, str],
    ) -> None:
        panes["w5:p1"] = " Allow edit?\n ❯ 1. Allow\n   2. Deny\n"

        response = call(
            port=port,
            method="POST",
            path="/keys",
            payload={"session_id": PERMISSION.session_id, "key": "1", "label": "Yes"},
        )

        assert (response.status, "Nothing was sent" in response.json()["error"], keys.calls) == (
            409,
            True,
            [],
        )

    def test_refuses_a_session_that_is_not_waiting(self, port: int, keys: KeySender) -> None:
        response = call(
            port=port,
            method="POST",
            path="/keys",
            payload={"session_id": IDLE.session_id, "key": "1", "label": "Yes"},
        )

        assert (response.status, keys.calls) == (409, [])

    def test_failure_reported(self, port: int, keys: KeySender) -> None:
        keys.error = ProbeError("herdr exited 1")

        response = call(
            port=port,
            method="POST",
            path="/keys",
            payload={"session_id": PERMISSION.session_id, "key": "1", "label": "Yes"},
        )

        assert (response.status, response.json()["error"]) == (502, "herdr exited 1")


class TestReply:
    def test_relays_text(self, port: int, app: SupervisorApp) -> None:
        response = call(
            port=port,
            method="POST",
            path="/reply",
            payload={"session_id": IDLE.session_id, "text": " Go with B "},
        )
        [message] = mailbox_unread(root=app.bus_root, name=RELAY)

        assert (response.json(), read_message(message=message)[1].strip()) == (
            {"ok": True},
            "Answer from Janusz: Go with B",
        )

    def test_empty_rejected(self, port: int) -> None:
        response = call(
            port=port,
            method="POST",
            path="/reply",
            payload={"session_id": IDLE.session_id, "text": "  "},
        )

        assert response.status == 400

    def test_unknown_session_conflicts(self, port: int) -> None:
        response = call(
            port=port, method="POST", path="/reply", payload={"session_id": "gone", "text": "hi"}
        )

        assert (response.status, response.json()) == (409, {"error": "That session is gone."})


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
        call(port=port, method="POST", path="/lessons", payload={**self.LESSON, "tags": "solo"})
        [lesson] = call(port=port, method="GET", path="/lessons").json()["lessons"]

        assert lesson["tags"] == ["solo"]

    def test_missing_fields(self, port: int) -> None:
        response = call(port=port, method="POST", path="/lessons", payload={"title": "x"})

        assert (response.status, "body, repo, topic" in response.json()["error"]) == (400, True)


class TestCollector:
    def test_refresh_reads_pane_for_needs_you(self, app: SupervisorApp) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[WAITING, IDLE], taken_at=NOW))

        assert app.pane_text == {"sid-wait": "working on it\n"}

    def test_refresh_bumps_the_version(self, app: SupervisorApp) -> None:
        before = app.version

        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))

        assert app.version == before + 1

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
        app.publish(snapshot=Snapshot(sessions=[busy], taken_at=NOW), pane_text={})
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
