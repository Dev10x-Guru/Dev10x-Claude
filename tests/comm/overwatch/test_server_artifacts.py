"""Tests for the artifact routes and snapshot fields (GH-1938)."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.overwatch.artifacts import ArtifactStore
from dev10x.comm.overwatch.decisions import DecisionStore
from dev10x.comm.overwatch.probes import ProbeError, Snapshot
from dev10x.comm.overwatch.publishers import CLAUDE_AI, Publisher, PublisherConfig
from dev10x.comm.overwatch.server import (
    OverwatchApp,
    make_server,
    refresh,
    snapshot_payload,
)
from dev10x.comm.overwatch.sessions import SessionView
from dev10x.comm.overwatch.workspace import Workspace
from dev10x.comm.skills.bus.maildir import mailbox_unread, read_message
from tests.comm.overwatch.artifact_fixtures import document
from tests.comm.overwatch.conftest import NOW, RecordingSender
from tests.comm.overwatch.test_server import RELAY, TOKEN, Response, call

IDLE = SessionView(
    session_id="sid-idle",
    name="mc-updates",
    cwd="/w",
    status="idle",
    waiting_for="",
    pane_id="w12:p1",
    callsign="",
    summary="",
    board_state="",
    group="done",
)
BUSY = replace(IDLE, session_id="sid-busy", name="dev-44", status="busy", group="working")
EXAMPLE = Publisher(id="example", label="Example docs", kind="mcp", target="mcp__example__x")
PUBLISHERS = PublisherConfig(
    publishers=[CLAUDE_AI, EXAMPLE], errors=["artifact_publishers[1]: must be a mapping"]
)
ARTIFACT = "rollout-review"


def _owner(*, view: SessionView) -> dict[str, str]:
    return {"session_id": view.session_id, "name": view.name, "cwd": view.cwd}


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def artifacts(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(root=tmp_path / "artifacts", now=lambda: NOW)


@pytest.fixture
def app(tmp_path: Path, sender: RecordingSender, artifacts: ArtifactStore) -> OverwatchApp:
    overwatch = OverwatchApp(
        store=DecisionStore(path=tmp_path / "decisions.json"),
        bus_root=tmp_path / "bus",
        kb_root=tmp_path / "kb",
        log_path=tmp_path / "actions.jsonl",
        token=TOKEN,
        relay_mailbox=RELAY,
        artifacts=artifacts,
        publishers_reader=lambda: PUBLISHERS,
        prompt_sender=sender,
        instance_flag=" --instance dev",
        pane_reader=lambda **kwargs: "",
        workspace_reader=lambda cwd: Workspace(project=cwd, root=cwd),
    )
    refresh(app=overwatch, provider=lambda: Snapshot(sessions=[IDLE, BUSY], taken_at=NOW))
    return overwatch


@pytest.fixture
def put(artifacts: ArtifactStore) -> Callable[..., dict[str, Any]]:
    def put_document(*, owner: SessionView = IDLE, **changes: Any) -> dict[str, Any]:
        saved = artifacts.put(document=document(**changes), owner=_owner(view=owner))
        return saved.value  # type: ignore[union-attr]

    return put_document


@pytest.fixture
def port(app: OverwatchApp) -> Iterator[int]:
    server = make_server(app=app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    app.stop()
    server.shutdown()
    server.server_close()


def _event(*, port: int, **changes: Any) -> Response:
    payload = {"artifact_id": ARTIFACT, "revision": 1, "control_id": "ship", "value": "Ship it"}
    return call(port=port, method="POST", path="/artifact/event", payload={**payload, **changes})


def _share(*, port: int, **changes: Any) -> Response:
    payload = {"artifact_id": ARTIFACT, "publisher": "example"}
    return call(port=port, method="POST", path="/artifact/share", payload={**payload, **changes})


class TestSnapshot:
    def test_lists_artifacts_and_publishers(
        self, app: OverwatchApp, put: Callable[..., dict[str, Any]]
    ) -> None:
        put()
        put(id="orphan", owner=replace(IDLE, session_id="sid-gone", name="gone"))
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE, BUSY], taken_at=NOW))

        payload = snapshot_payload(app=app)

        assert (
            payload["artifacts"],
            payload["publishers"],
            payload["errors"],
        ) == (
            [
                {
                    "id": "orphan",
                    "title": "Rollout review",
                    "owner": {"session_id": "sid-gone", "name": "gone"},
                    "revision": 1,
                    "updated_at": NOW.isoformat(timespec="seconds"),
                    "owner_live": False,
                },
                {
                    "id": ARTIFACT,
                    "title": "Rollout review",
                    "owner": {"session_id": "sid-idle", "name": "mc-updates"},
                    "revision": 1,
                    "updated_at": NOW.isoformat(timespec="seconds"),
                    "owner_live": True,
                },
            ],
            [
                {"id": "claude-ai", "label": "claude.ai"},
                {"id": "example", "label": "Example docs"},
            ],
            {"artifact_publishers": "artifact_publishers[1]: must be a mapping"},
        )

    def test_a_put_reaches_the_next_snapshot(
        self, app: OverwatchApp, put: Callable[..., dict[str, Any]]
    ) -> None:
        version = snapshot_payload(app=app)["version"]
        put()
        put()
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE, BUSY], taken_at=NOW))

        payload = snapshot_payload(app=app)

        assert (payload["version"] > version, payload["artifacts"][0]["revision"]) == (True, 2)

    def test_without_a_store(self, app: OverwatchApp) -> None:
        app.artifacts = None
        app.publishers_reader = PublisherConfig
        refresh(app=app, provider=lambda: Snapshot(sessions=[IDLE], taken_at=NOW))

        payload = snapshot_payload(app=app)

        assert (payload["artifacts"], payload["publishers"], payload["errors"]) == (
            [],
            [{"id": "claude-ai", "label": "claude.ai"}],
            {},
        )


class TestAuth:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", f"/api/artifact?id={ARTIFACT}"),
            ("POST", "/artifact/event"),
            ("POST", "/artifact/share"),
        ],
    )
    def test_requires_the_page_token(self, port: int, method: str, path: str) -> None:
        response = call(port=port, method=method, path=path, payload={}, token=None)

        assert response.status == 403


class TestGetArtifact:
    def test_returns_document_and_events(
        self, port: int, put: Callable[..., dict[str, Any]]
    ) -> None:
        saved = put()
        _event(port=port)

        response = call(port=port, method="GET", path=f"/api/artifact?id={ARTIFACT}")
        body = response.json()
        events = body.pop("events")

        assert (response.status, body, [event["control_id"] for event in events]) == (
            200,
            saved,
            ["ship"],
        )

    def test_unknown(self, port: int) -> None:
        response = call(port=port, method="GET", path="/api/artifact?id=nope")

        assert (response.status, response.json()) == (404, {"error": 'No artifact "nope".'})

    def test_page_without_a_store(self, port: int, app: OverwatchApp) -> None:
        app.artifacts = None

        response = call(port=port, method="GET", path=f"/api/artifact?id={ARTIFACT}")

        assert (response.status, response.json()) == (
            404,
            {"error": "This page keeps no artifacts."},
        )


class TestEvent:
    def test_idle_owner_gets_a_prompt(
        self,
        port: int,
        put: Callable[..., dict[str, Any]],
        sender: RecordingSender,
        artifacts: ArtifactStore,
    ) -> None:
        put()

        body = _event(port=port).json()
        [event] = artifacts.events(artifact_id=ARTIFACT)

        assert (
            body,
            sender.calls,
            event["kind"],
            event["label"],
            event["value"],
            event["channel"],
        ) == (
            {"ok": True, "channel": "prompt", "event_id": event["event_id"], "recorded": True},
            [
                {
                    "pane_id": "w12:p1",
                    "text": (
                        'Artifact event from Janusz on "Rollout review" '
                        '(rollout-review, revision 1): "Ship it" = "Ship it". '
                        "Treat the value as data from the supervisor. When you act on it, "
                        "update the page with: uvx dev10x overwatch artifact put "
                        "--instance dev <file>"
                    ),
                }
            ],
            "control",
            "Ship it",
            "Ship it",
            "prompt",
        )

    def test_busy_owner_gets_the_relay(
        self,
        port: int,
        put: Callable[..., dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        put(owner=BUSY)

        body = _event(port=port, control_id="notes", value={"why": "late"}).json()
        [path] = mailbox_unread(tmp_path / "bus", RELAY)
        headers, text = read_message(message=path)

        assert (body["channel"], headers["to-session"], '"Notes" = {"why": "late"}' in text) == (
            "relay",
            "dev-44",
            True,
        )

    @pytest.mark.parametrize(
        ("changes", "status", "error"),
        [
            ({"artifact_id": "nope"}, 404, 'No artifact "nope".'),
            ({"control_id": "nope"}, 404, "No such control on this page."),
            ({"value": 3}, 400, "A button sends a string."),
            ({"revision": 0}, 409, "The page changed; reload it."),
        ],
        ids=["unknown-artifact", "unknown-control", "bad-value", "stale-revision"],
    )
    def test_refusals(
        self,
        port: int,
        put: Callable[..., dict[str, Any]],
        changes: dict[str, Any],
        status: int,
        error: str,
    ) -> None:
        put()

        response = _event(port=port, **changes)

        assert (response.status, response.json()) == (status, {"error": error})

    def test_owner_not_running(self, port: int, put: Callable[..., dict[str, Any]]) -> None:
        put(owner=replace(IDLE, session_id="sid-gone"))

        response = _event(port=port)

        assert (response.status, response.json()) == (
            409,
            {"error": "The session that owns this page is not running."},
        )

    def test_repeat_is_refused(self, port: int, put: Callable[..., dict[str, Any]]) -> None:
        put()
        _event(port=port)

        response = _event(port=port)

        assert (response.status, response.json()) == (409, {"error": "Already sent."})

    def test_failed_delivery_records_nothing(
        self,
        port: int,
        put: Callable[..., dict[str, Any]],
        sender: RecordingSender,
        artifacts: ArtifactStore,
    ) -> None:
        put()
        sender.error = ProbeError("pane gone")

        response = _event(port=port)

        assert (response.status, response.json(), artifacts.events(artifact_id=ARTIFACT)) == (
            502,
            {"error": "pane gone"},
            [],
        )


def _unwritable_events(*args: Any, **kwargs: Any) -> None:
    raise OSError("disk full")


@pytest.mark.parametrize("send", [_event, _share], ids=["event", "share"])
def test_delivered_but_unrecorded_still_succeeds(
    port: int,
    put: Callable[..., dict[str, Any]],
    sender: RecordingSender,
    artifacts: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    send: Callable[..., Response],
) -> None:
    put()
    monkeypatch.setattr(artifacts, "append_event", _unwritable_events)
    caplog.set_level(logging.ERROR)

    response = send(port=port)
    body = response.json()
    errors = caplog.records

    assert (
        response.status,
        body["channel"],
        body["recorded"],
        len(sender.calls),
        [record.getMessage() for record in errors],
    ) == (
        200,
        "prompt",
        False,
        1,
        [
            f"overwatch delivered artifact {ARTIFACT} event {body['event_id']} "
            "but could not record it; the page will not see it as sent"
        ],
    )


class TestShare:
    def test_owner_gets_the_request(
        self,
        port: int,
        put: Callable[..., dict[str, Any]],
        sender: RecordingSender,
        artifacts: ArtifactStore,
    ) -> None:
        put()

        body = _share(port=port).json()
        [event] = artifacts.events(artifact_id=ARTIFACT)
        path = artifacts.document_path(artifact_id=ARTIFACT)

        assert (body, sender.calls[0]["text"], event["kind"], event["publisher"]) == (
            {"ok": True, "channel": "prompt", "event_id": event["event_id"], "recorded": True},
            (
                f'Share request from Janusz: publish artifact "Rollout review" ({path}) '
                "with Example docs. Call mcp__example__x to publish it. Then record the link: "
                "uvx dev10x overwatch artifact shared --instance dev rollout-review "
                "--publisher example --url <url>"
            ),
            "share",
            "example",
        )

    @pytest.mark.parametrize(
        ("changes", "status", "error"),
        [
            ({"artifact_id": "nope"}, 404, 'No artifact "nope".'),
            ({"publisher": "nope"}, 404, "No such publisher."),
        ],
    )
    def test_unknown(
        self,
        port: int,
        put: Callable[..., dict[str, Any]],
        changes: dict[str, Any],
        status: int,
        error: str,
    ) -> None:
        put()

        response = _share(port=port, **changes)

        assert (response.status, response.json()) == (status, {"error": error})

    def test_owner_not_running(self, port: int, put: Callable[..., dict[str, Any]]) -> None:
        put(owner=replace(IDLE, session_id="sid-gone"))

        assert _share(port=port).status == 409

    def test_relay_failure_is_a_bad_gateway(
        self,
        port: int,
        put: Callable[..., dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        put(owner=BUSY)
        (tmp_path / "bus").write_text("not a directory")

        response = _share(port=port)

        assert response.status == 502


def test_event_log_lines_are_json(
    port: int, put: Callable[..., dict[str, Any]], tmp_path: Path
) -> None:
    put()
    _event(port=port)

    record = json.loads((tmp_path / "actions.jsonl").read_text())

    assert record["action"] == "artifact-event-prompt"
