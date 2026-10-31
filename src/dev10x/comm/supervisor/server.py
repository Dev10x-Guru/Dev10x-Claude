from __future__ import annotations

import hmac
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from dev10x.comm.supervisor.decisions import ANSWERED, OPEN, Decision, DecisionStore
from dev10x.comm.supervisor.delivery import (
    deliver_keys,
    deliver_relay,
    keys_for_option,
    keys_for_permission,
)
from dev10x.comm.supervisor.lessons import find_lessons, write_lesson
from dev10x.comm.supervisor.page import PERMISSION_PROMPT, render_page
from dev10x.comm.supervisor.paths import TOKEN_HEADER
from dev10x.comm.supervisor.probes import ProbeError, Snapshot, read_pane, send_keys
from dev10x.comm.supervisor.sessions import SessionView

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024
CONFIRMED_BY = "janusz"


class RequestError(Exception):
    def __init__(self, *, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class SupervisorApp:
    store: DecisionStore
    bus_root: Path
    kb_root: Path
    log_path: Path
    token: str
    relay_mailbox: str
    key_sender: Callable[..., None] = send_keys
    pane_reader: Callable[..., str] = read_pane
    today: Callable[[], date] = date.today
    snapshot: Snapshot = field(default_factory=lambda: Snapshot(sessions=[]))
    pane_text: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def session(self, *, session_id: str) -> SessionView | None:
        with self.lock:
            sessions = self.snapshot.sessions
        return next((view for view in sessions if view.session_id == session_id), None)


def refresh(*, app: SupervisorApp, provider: Callable[[], Snapshot]) -> None:
    snapshot = provider()
    with app.lock:
        previous = {view.session_id: view.status for view in app.snapshot.sessions}
    pane_text = {
        view.session_id: app.pane_reader(pane_id=view.pane_id)
        for view in snapshot.sessions
        if view.group == "needs-you" and view.pane_id
    }
    status = {view.session_id: view.status for view in snapshot.sessions}
    for decision in app.store.all():
        now = status.get(decision.session_id, "gone")
        if decision.state == ANSWERED and _delivered(channel=decision.channel, status=now):
            app.store.mark_delivered(decision_id=decision.decision_id)
        left_waiting = previous.get(decision.session_id) == "waiting" and now != "waiting"
        if decision.state == OPEN and left_waiting:
            app.store.expire_for_session(session_id=decision.session_id)
    with app.lock:
        app.snapshot = snapshot
        app.pane_text = pane_text


def _delivered(*, channel: str, status: str) -> bool:
    if channel == "keys":
        return status != "waiting"
    return status in ("busy", "gone")


def run_collector(
    *,
    app: SupervisorApp,
    interval: float,
    stop: threading.Event,
    provider: Callable[[], Snapshot],
) -> None:
    while not stop.is_set():
        try:
            refresh(app=app, provider=provider)
        except Exception:
            log.exception("supervisor collector tick failed")
        stop.wait(interval)


class SupervisorHandler(BaseHTTPRequestHandler):
    server: SupervisorServer

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("supervisor %s", format % args)

    @property
    def app(self) -> SupervisorApp:
        return self.server.app

    def do_GET(self) -> None:
        self._dispatch(
            routes={"/": self._page, "/api/sessions": self._api, "/lessons": self._lessons}
        )

    def do_POST(self) -> None:
        self._dispatch(
            routes={
                "/decisions": self._post_decisions,
                "/answer": self._post_answer,
                "/keys": self._post_keys,
                "/reply": self._post_reply,
                "/lessons": self._post_lesson,
            }
        )

    def _dispatch(self, *, routes: dict[str, Callable[[dict[str, str]], None]]) -> None:
        url = urlsplit(self.path)
        handler = routes.get(url.path)
        try:
            if handler is None:
                raise RequestError(status=HTTPStatus.NOT_FOUND, message="no such route")
            params = self._params(query=url.query)
            self._check_token(params=params)
            handler(params)
        except RequestError as exc:
            self._send(status=exc.status, body=exc.message, content_type="text/plain")

    def _params(self, *, query: str) -> dict[str, str]:
        params = {key: values[-1] for key, values in parse_qs(query).items()}
        if self.command != "POST":
            return params
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise RequestError(
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, message="body too large"
            )
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        if self.headers.get("Content-Type", "").startswith("application/json"):
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                raise RequestError(status=HTTPStatus.BAD_REQUEST, message=f"bad JSON: {exc}")
            if not isinstance(payload, dict):
                raise RequestError(status=HTTPStatus.BAD_REQUEST, message="JSON must be an object")
            self.json_body = payload
            return params
        params.update({key: values[-1] for key, values in parse_qs(raw).items()})
        return params

    def _check_token(self, *, params: dict[str, str]) -> None:
        offered = self.headers.get(TOKEN_HEADER) or params.get("token", "")
        if not hmac.compare_digest(offered.encode(), self.app.token.encode()):
            raise RequestError(status=HTTPStatus.FORBIDDEN, message="missing or wrong token")

    def _send(self, *, status: HTTPStatus, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, *, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._send(status=status, body=json.dumps(payload), content_type="application/json")

    def _back_to_page(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/?token={self.app.token}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _page(self, params: dict[str, str]) -> None:
        with self.app.lock:
            snapshot, pane_text = self.app.snapshot, dict(self.app.pane_text)
        open_decisions = [d for d in self.app.store.all() if d.state == OPEN]
        html = render_page(
            snapshot=snapshot,
            decisions=open_decisions,
            pane_text=pane_text,
            token=self.app.token,
        )
        self._send(status=HTTPStatus.OK, body=html, content_type="text/html")

    def _api(self, params: dict[str, str]) -> None:
        with self.app.lock:
            snapshot = self.app.snapshot
        self._json(
            status=HTTPStatus.OK,
            payload={
                "sessions": [asdict(view) for view in snapshot.sessions],
                "errors": snapshot.errors,
                "decisions": [asdict(decision) for decision in self.app.store.all()],
            },
        )

    def _lessons(self, params: dict[str, str]) -> None:
        found = find_lessons(
            kb_root=self.app.kb_root,
            repo=params.get("repo", ""),
            query=params.get("q", ""),
        )
        self._json(status=HTTPStatus.OK, payload={"lessons": [asdict(item) for item in found]})

    def _body(self) -> dict[str, Any]:
        body = getattr(self, "json_body", None)
        if body is None:
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message="expected a JSON body")
        return body

    def _post_decisions(self, params: dict[str, str]) -> None:
        body = self._body()
        questions = body.get("questions")
        if not body.get("session_id") or not isinstance(questions, list):
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST, message="session_id and questions are required"
            )
        added = self.app.store.add_from_hook(
            session_id=str(body["session_id"]),
            cwd=str(body.get("cwd", "")),
            questions=[question for question in questions if isinstance(question, dict)],
        )
        self._json(
            status=HTTPStatus.CREATED,
            payload={"decision_ids": [decision.decision_id for decision in added]},
        )

    def _waiting_session(self, *, session_id: str) -> SessionView:
        view = self.app.session(session_id=session_id)
        if view is None:
            raise RequestError(status=HTTPStatus.CONFLICT, message="session is no longer listed")
        return view

    def _post_answer(self, params: dict[str, str]) -> None:
        decision = self.app.store.get(decision_id=params.get("decision_id", ""))
        if decision is None or decision.state != OPEN:
            raise RequestError(status=HTTPStatus.CONFLICT, message="decision is not open")
        view = self._waiting_session(session_id=decision.session_id)
        index = _option_index(raw=params.get("option_index", ""), decision=decision)
        answer = decision.options[index]
        if view.status == "waiting" and view.pane_id:
            self._answer_by_keys(decision=decision, view=view, index=index, answer=answer)
        else:
            self._answer_by_relay(decision=decision, view=view, answer=answer)
        self._back_to_page()

    def _answer_by_keys(
        self,
        *,
        decision: Decision,
        view: SessionView,
        index: int,
        answer: str,
    ) -> None:
        if (
            self.app.store.answer(decision_id=decision.decision_id, answer=answer, channel="keys")
            is None
        ):
            raise RequestError(status=HTTPStatus.CONFLICT, message="decision already answered")
        try:
            deliver_keys(
                pane_id=view.pane_id,
                keys=keys_for_option(index=index),
                confirmed_by=CONFIRMED_BY,
                log_path=self.app.log_path,
                sender=self.app.key_sender,
            )
        except ProbeError as exc:
            self.app.store.reopen(decision_id=decision.decision_id)
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc

    def _answer_by_relay(self, *, decision: Decision, view: SessionView, answer: str) -> None:
        if (
            self.app.store.answer(decision_id=decision.decision_id, answer=answer, channel="relay")
            is None
        ):
            raise RequestError(status=HTTPStatus.CONFLICT, message="decision already answered")
        deliver_relay(
            bus_root=self.app.bus_root,
            relay_mailbox=self.app.relay_mailbox,
            session_name=view.name,
            session_id=view.session_id,
            decision_id=decision.decision_id,
            answer=answer,
            confirmed_by=CONFIRMED_BY,
            log_path=self.app.log_path,
        )

    def _post_keys(self, params: dict[str, str]) -> None:
        view = self._waiting_session(session_id=params.get("session_id", ""))
        if view.waiting_for != PERMISSION_PROMPT or not view.pane_id:
            raise RequestError(
                status=HTTPStatus.CONFLICT, message="session is not on a permission prompt"
            )
        try:
            deliver_keys(
                pane_id=view.pane_id,
                keys=keys_for_permission(allow=params.get("allow") == "1"),
                confirmed_by=CONFIRMED_BY,
                log_path=self.app.log_path,
                sender=self.app.key_sender,
            )
        except ProbeError as exc:
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc
        self._back_to_page()

    def _post_reply(self, params: dict[str, str]) -> None:
        view = self._waiting_session(session_id=params.get("session_id", ""))
        text = params.get("text", "").strip()
        if not text:
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message="reply text is empty")
        deliver_relay(
            bus_root=self.app.bus_root,
            relay_mailbox=self.app.relay_mailbox,
            session_name=view.name,
            session_id=view.session_id,
            decision_id=f"{view.session_id[:8]}-reply",
            answer=text,
            confirmed_by=CONFIRMED_BY,
            log_path=self.app.log_path,
        )
        self._back_to_page()

    def _post_lesson(self, params: dict[str, str]) -> None:
        body = self._body()
        missing = [name for name in ("title", "body", "repo", "topic") if not body.get(name)]
        if missing:
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST, message=f"missing fields: {', '.join(missing)}"
            )
        tags = body.get("tags") or []
        path = write_lesson(
            kb_root=self.app.kb_root,
            title=str(body["title"]),
            body=str(body["body"]),
            repo=str(body["repo"]),
            topic=str(body["topic"]),
            tags=[str(tag) for tag in tags] if isinstance(tags, list) else [str(tags)],
            source_session=str(body.get("source_session", "")),
            today=self.app.today(),
        )
        self._json(status=HTTPStatus.CREATED, payload={"path": str(path)})


def _option_index(*, raw: str, decision: Decision) -> int:
    try:
        index = int(raw)
    except ValueError as exc:
        raise RequestError(
            status=HTTPStatus.BAD_REQUEST, message="option_index is not a number"
        ) from exc
    if not 0 <= index < len(decision.options):
        raise RequestError(status=HTTPStatus.BAD_REQUEST, message="option_index out of range")
    return index


class SupervisorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *, app: SupervisorApp, port: int) -> None:
        super().__init__((HOST, port), SupervisorHandler)
        self.app = app


def make_server(*, app: SupervisorApp, port: int) -> SupervisorServer:
    return SupervisorServer(app=app, port=port)
