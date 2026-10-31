from __future__ import annotations

import hmac
import json
import logging
import mimetypes
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
from dev10x.comm.supervisor.delivery import deliver_keys, deliver_relay, keys_for_option
from dev10x.comm.supervisor.lessons import find_lessons, write_lesson
from dev10x.comm.supervisor.paths import TOKEN_HEADER
from dev10x.comm.supervisor.probes import ProbeError, Snapshot, read_pane, send_keys
from dev10x.comm.supervisor.prompts import find_option, parse_prompt
from dev10x.comm.supervisor.sessions import SessionView

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024
CONFIRMED_BY = "janusz"
STATIC_DIR = Path(__file__).parent / "static"
HEARTBEAT_SECONDS = 15.0
EXCERPT_LINES = 24


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
    static_dir: Path = STATIC_DIR
    snapshot: Snapshot = field(default_factory=lambda: Snapshot(sessions=[]))
    pane_text: dict[str, str] = field(default_factory=dict)
    version: int = 0
    stopping: threading.Event = field(default_factory=threading.Event)
    changed: threading.Condition = field(default_factory=threading.Condition)

    def session(self, *, session_id: str) -> SessionView | None:
        with self.changed:
            sessions = self.snapshot.sessions
        return next((view for view in sessions if view.session_id == session_id), None)

    def publish(self, *, snapshot: Snapshot, pane_text: dict[str, str]) -> None:
        with self.changed:
            self.snapshot = snapshot
            self.pane_text = pane_text
            self.version += 1
            self.changed.notify_all()

    def nudge(self) -> None:
        with self.changed:
            self.version += 1
            self.changed.notify_all()

    def stop(self) -> None:
        self.stopping.set()
        self.nudge()


def _excerpt(*, text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines[-EXCERPT_LINES:])


def snapshot_payload(*, app: SupervisorApp) -> dict[str, Any]:
    with app.changed:
        snapshot, pane_text, version = app.snapshot, dict(app.pane_text), app.version
    open_decisions = [decision for decision in app.store.all() if decision.state == OPEN]
    sessions = []
    for view in snapshot.sessions:
        text = pane_text.get(view.session_id, "")
        prompt = parse_prompt(pane_text=text) if view.status == "waiting" else None
        sessions.append(
            {
                **asdict(view),
                "prompt": asdict(prompt) if prompt else None,
                "excerpt": _excerpt(text=text),
                "decisions": [
                    asdict(decision)
                    for decision in open_decisions
                    if decision.session_id == view.session_id
                ],
            }
        )
    return {
        "version": version,
        "taken_at": snapshot.taken_at.isoformat(timespec="seconds"),
        "errors": snapshot.errors,
        "sessions": sessions,
    }


def refresh(*, app: SupervisorApp, provider: Callable[[], Snapshot]) -> None:
    snapshot = provider()
    with app.changed:
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
    app.publish(snapshot=snapshot, pane_text=pane_text)


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
    json_body: dict[str, Any] | None = None

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("supervisor %s", format % args)

    @property
    def app(self) -> SupervisorApp:
        return self.server.app

    def do_GET(self) -> None:
        if urlsplit(self.path).path.startswith("/assets/"):
            self._asset()
            return
        self._dispatch(
            routes={
                "/": self._page,
                "/api/sessions": self._api,
                "/api/events": self._events,
                "/lessons": self._lessons,
            }
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
            self._json(status=exc.status, payload={"error": exc.message})

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
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return params
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message=f"bad JSON: {exc}")
        if not isinstance(payload, dict):
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message="JSON must be an object")
        self.json_body = payload
        return params

    def _check_token(self, *, params: dict[str, str]) -> None:
        offered = self.headers.get(TOKEN_HEADER) or params.get("token", "")
        if not hmac.compare_digest(offered.encode(), self.app.token.encode()):
            raise RequestError(status=HTTPStatus.FORBIDDEN, message="missing or wrong token")

    def _send(self, *, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, *, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._send(
            status=status,
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    def _ok(self, **payload: Any) -> None:
        self._json(status=HTTPStatus.OK, payload={"ok": True, **payload})

    def _page(self, params: dict[str, str]) -> None:
        index = self.app.static_dir / "index.html"
        if not index.is_file():
            raise RequestError(
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                message="the supervisor page is not built; run pnpm build in frontend/supervisor",
            )
        self._send(
            status=HTTPStatus.OK, body=index.read_bytes(), content_type="text/html; charset=utf-8"
        )

    def _asset(self) -> None:
        root = (self.app.static_dir / "assets").resolve()
        relative = urlsplit(self.path).path.removeprefix("/assets/")
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            self._json(status=HTTPStatus.NOT_FOUND, payload={"error": "no such asset"})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(status=HTTPStatus.OK, body=target.read_bytes(), content_type=content_type)

    def _api(self, params: dict[str, str]) -> None:
        self._json(status=HTTPStatus.OK, payload=snapshot_payload(app=self.app))

    def _events(self, params: dict[str, str]) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        seen = -1
        try:
            while not self.app.stopping.is_set():
                with self.app.changed:
                    if self.app.version == seen:
                        self.app.changed.wait(timeout=HEARTBEAT_SECONDS)
                    current = self.app.version
                if self.app.stopping.is_set():
                    break
                if current == seen:
                    self.wfile.write(b": ping\n\n")
                else:
                    seen = current
                    data = json.dumps(snapshot_payload(app=self.app))
                    self.wfile.write(f"event: snapshot\ndata: {data}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _lessons(self, params: dict[str, str]) -> None:
        found = find_lessons(
            kb_root=self.app.kb_root,
            repo=params.get("repo", ""),
            query=params.get("q", ""),
        )
        self._json(status=HTTPStatus.OK, payload={"lessons": [asdict(item) for item in found]})

    def _body(self) -> dict[str, Any]:
        if self.json_body is None:
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message="expected a JSON body")
        return self.json_body

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
        self.app.nudge()
        self._json(
            status=HTTPStatus.CREATED,
            payload={"decision_ids": [decision.decision_id for decision in added]},
        )

    def _listed_session(self, *, session_id: str) -> SessionView:
        view = self.app.session(session_id=session_id)
        if view is None:
            raise RequestError(status=HTTPStatus.CONFLICT, message="That session is gone.")
        return view

    def _post_answer(self, params: dict[str, str]) -> None:
        body = self._body()
        decision = self.app.store.get(decision_id=str(body.get("decision_id", "")))
        if decision is None or decision.state != OPEN:
            raise RequestError(status=HTTPStatus.CONFLICT, message="Already answered.")
        view = self._listed_session(session_id=decision.session_id)
        index = _option_index(raw=body.get("option_index"), decision=decision)
        answer = decision.options[index]
        by_keys = view.status == "waiting" and bool(view.pane_id)
        if by_keys:
            self._answer_by_keys(decision=decision, view=view, index=index, answer=answer)
        else:
            self._answer_by_relay(decision=decision, view=view, answer=answer)
        self.app.nudge()
        self._ok(channel="keys" if by_keys else "relay")

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
            raise RequestError(status=HTTPStatus.CONFLICT, message="Already answered.")
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
            raise RequestError(status=HTTPStatus.CONFLICT, message="Already answered.")
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
        body = self._body()
        view = self._listed_session(session_id=str(body.get("session_id", "")))
        if view.status != "waiting" or not view.pane_id:
            raise RequestError(
                status=HTTPStatus.CONFLICT, message="That session is no longer waiting."
            )
        key, label = str(body.get("key", "")), str(body.get("label", ""))
        live = parse_prompt(pane_text=self.app.pane_reader(pane_id=view.pane_id))
        if find_option(prompt=live, key=key, label=label) is None:
            raise RequestError(
                status=HTTPStatus.CONFLICT,
                message="The prompt changed before the key was sent. Nothing was sent.",
            )
        try:
            deliver_keys(
                pane_id=view.pane_id,
                keys=[key],
                confirmed_by=CONFIRMED_BY,
                log_path=self.app.log_path,
                sender=self.app.key_sender,
            )
        except ProbeError as exc:
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc
        self._ok(sent=key)

    def _post_reply(self, params: dict[str, str]) -> None:
        body = self._body()
        view = self._listed_session(session_id=str(body.get("session_id", "")))
        text = str(body.get("text", "")).strip()
        if not text:
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message="The reply is empty.")
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
        self._ok()

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


def _option_index(*, raw: object, decision: Decision) -> int:
    try:
        index = int(str(raw))
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
