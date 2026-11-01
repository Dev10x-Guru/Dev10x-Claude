from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from dev10x.comm.skills.bus.maildir import InvalidMessageError
from dev10x.comm.supervisor.decisions import (
    ANSWERED,
    HOOK_CHANNEL,
    OPEN,
    Decision,
    DecisionStore,
    is_held,
)
from dev10x.comm.supervisor.delivery import (
    SESSION_COMMANDS,
    Peer,
    deliver_keys,
    deliver_relay,
    introduce,
    keys_for_option,
    log_action,
    rename_session,
    request_preapproval,
    run_session_command,
)
from dev10x.comm.supervisor.history import PastSession, read_past_sessions
from dev10x.comm.supervisor.launcher import (
    Launched,
    LaunchError,
    Project,
    create_worktree,
    open_session,
    read_project,
)
from dev10x.comm.supervisor.lessons import find_lessons, write_lesson
from dev10x.comm.supervisor.naming import Rename, is_valid_name, plan_renames
from dev10x.comm.supervisor.paths import TOKEN_HEADER
from dev10x.comm.supervisor.pending import (
    ConversationEntry,
    Preview,
    RecentTool,
    read_conversation,
    read_preview,
    read_recent_tools,
    read_session_commands,
)
from dev10x.comm.supervisor.probes import ProbeError, Snapshot, read_pane, send_keys
from dev10x.comm.supervisor.prompts import (
    find_option,
    parse_prompt,
    parse_status_line_ansi,
    strip_ansi,
)
from dev10x.comm.supervisor.session_tasks import SessionTask, read_session_tasks
from dev10x.comm.supervisor.sessions import SessionView
from dev10x.comm.supervisor.settings import PageSettings, SettingsStore
from dev10x.comm.supervisor.workspace import (
    Workspace,
    issue_url,
    pr_number,
    pr_url,
    read_workspace,
)

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024
CONFIRMED_BY = "janusz"
AUTO_RENAMED_BY = "janusz (daemon start)"
STATIC_DIR = Path(__file__).parent / "static"
HEARTBEAT_SECONDS = 15.0
HOOK_ROUTES = frozenset({"/decisions", "/decisions/answers", "/decisions/release"})
HELD_WAITING_FOR = "your answer on this page"
EXCERPT_LINES = 24
TAIL_LINES = 400
TAIL_SOURCE = "recent-unwrapped"
STATUS_LINE_SECONDS = 30.0
STATUS_LINE_WORKERS = 8


def _local_now() -> datetime:
    return datetime.now().astimezone()


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
    hook_token: str = ""
    settings: SettingsStore | None = None
    now: Callable[[], datetime] = _local_now
    key_sender: Callable[..., None] = send_keys
    pane_reader: Callable[..., str] = read_pane
    preview_reader: Callable[..., Preview | None] = read_preview
    commands_reader: Callable[..., list[str]] = read_session_commands
    recent_reader: Callable[..., list[RecentTool]] = read_recent_tools
    conversation_reader: Callable[..., list[ConversationEntry]] = read_conversation
    tasks_reader: Callable[..., list[SessionTask]] = read_session_tasks
    workspace_reader: Callable[..., Workspace] = read_workspace
    renamer: Callable[..., None] = rename_session
    commander: Callable[..., None] = run_session_command
    project_reader: Callable[..., Project] = read_project
    past_reader: Callable[..., list[PastSession]] = read_past_sessions
    opener: Callable[..., Launched] = open_session
    worktree_maker: Callable[..., Launched] = create_worktree
    auto_rename: bool = False
    auto_renamed: bool = False
    today: Callable[[], date] = date.today
    clock: Callable[[], float] = time.monotonic
    static_dir: Path = STATIC_DIR
    snapshot: Snapshot = field(default_factory=lambda: Snapshot(sessions=[]))
    pane_text: dict[str, str] = field(default_factory=dict)
    previews: dict[str, Preview] = field(default_factory=dict)
    status_lines: dict[str, str] = field(default_factory=dict)
    status_lines_read_at: float | None = None
    workspaces: dict[str, Workspace] = field(default_factory=dict)
    version: int = 0
    stopping: threading.Event = field(default_factory=threading.Event)
    changed: threading.Condition = field(default_factory=threading.Condition)

    def session(self, *, session_id: str) -> SessionView | None:
        with self.changed:
            sessions = self.snapshot.sessions
        return next((view for view in sessions if view.session_id == session_id), None)

    def publish(
        self,
        *,
        snapshot: Snapshot,
        pane_text: dict[str, str],
        previews: dict[str, Preview] | None = None,
        status_lines: dict[str, str] | None = None,
        workspaces: dict[str, Workspace] | None = None,
    ) -> None:
        with self.changed:
            self.snapshot = snapshot
            self.pane_text = pane_text
            self.previews = previews or {}
            self.status_lines = status_lines or {}
            self.workspaces = workspaces or {}
            self.version += 1
            self.changed.notify_all()

    def page_settings(self) -> PageSettings:
        return self.settings.load() if self.settings else PageSettings()

    def nudge(self) -> None:
        with self.changed:
            self.version += 1
            self.changed.notify_all()

    def stop(self) -> None:
        self.stopping.set()
        self.nudge()


def _excerpt(*, text: str, lines: int = EXCERPT_LINES) -> str:
    rows = [line.rstrip() for line in text.splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return "\n".join(rows[-lines:])


def _workspace_payload(
    *,
    workspace: Workspace | None,
    cwd: str,
    status_line: str,
) -> dict[str, str]:
    workspace = workspace or Workspace(project=Path(cwd).name or cwd, root=cwd)
    pr = pr_number(status_line=status_line)
    return {
        **asdict(workspace),
        "issue_url": issue_url(issue=workspace.issue, repo_url=workspace.repo_url),
        "pr": pr,
        "pr_url": pr_url(pr=pr, repo_url=workspace.repo_url),
    }


def snapshot_payload(*, app: SupervisorApp) -> dict[str, Any]:
    with app.changed:
        snapshot, pane_text, version = app.snapshot, dict(app.pane_text), app.version
        previews, status_lines = dict(app.previews), dict(app.status_lines)
        workspaces = dict(app.workspaces)
    open_decisions = [decision for decision in app.store.all() if decision.state == OPEN]
    now = app.now()
    held = {
        decision.session_id for decision in open_decisions if is_held(decision=decision, now=now)
    }
    sessions = []
    for listed in snapshot.sessions:
        view = _held_view(view=listed) if listed.session_id in held else listed
        text = pane_text.get(view.session_id, "")
        prompt = parse_prompt(pane_text=text) if view.status == "waiting" else None
        preview = previews.get(view.session_id)
        status_line_ansi = status_lines.get(view.session_id, "")
        status_line = strip_ansi(status_line_ansi)
        sessions.append(
            {
                **asdict(view),
                "prompt": asdict(prompt) if prompt else None,
                "preview": asdict(preview) if preview else None,
                "excerpt": _excerpt(text=text),
                "status_line": status_line,
                "status_line_ansi": status_line_ansi,
                "workspace": _workspace_payload(
                    workspace=workspaces.get(view.cwd), cwd=view.cwd, status_line=status_line
                ),
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
        "settings": asdict(app.page_settings()),
    }


def _held_view(*, view: SessionView) -> SessionView:
    return replace(view, status="waiting", waiting_for=HELD_WAITING_FOR, group="needs-you")


def _slow_read_due(*, app: SupervisorApp) -> bool:
    now = app.clock()
    with app.changed:
        read_at = app.status_lines_read_at
        due = read_at is None or now - read_at >= STATUS_LINE_SECONDS
        if due:
            app.status_lines_read_at = now
    return due


def _status_lines(
    *,
    app: SupervisorApp,
    sessions: list[SessionView],
    pane_ansi: dict[str, str],
    due: bool,
) -> dict[str, str]:
    with app.changed:
        cached = dict(app.status_lines)
    screens = dict(pane_ansi)
    if due:
        unread = [view for view in sessions if view.pane_id and view.session_id not in screens]
        with ThreadPoolExecutor(max_workers=STATUS_LINE_WORKERS) as pool:
            read = pool.map(lambda view: app.pane_reader(pane_id=view.pane_id, ansi=True), unread)
            screens.update(zip((view.session_id for view in unread), read, strict=True))
    lines = {}
    for view in sessions:
        line = parse_status_line_ansi(pane_ansi=screens.get(view.session_id, ""))
        lines[view.session_id] = line or cached.get(view.session_id, "")
    return lines


def _workspaces(
    *,
    app: SupervisorApp,
    sessions: list[SessionView],
    due: bool,
) -> dict[str, Workspace]:
    with app.changed:
        cached = dict(app.workspaces)
    cwds = sorted({view.cwd for view in sessions})
    stale = [cwd for cwd in cwds if due or cwd not in cached]
    with ThreadPoolExecutor(max_workers=STATUS_LINE_WORKERS) as pool:
        cached.update(zip(stale, pool.map(lambda cwd: app.workspace_reader(cwd=cwd), stale)))
    return {cwd: cached[cwd] for cwd in cwds}


def refresh(*, app: SupervisorApp, provider: Callable[[], Snapshot]) -> None:
    snapshot = provider()
    with app.changed:
        previous = {view.session_id: view.status for view in app.snapshot.sessions}
        previous_taken_at = app.snapshot.taken_at
    pane_ansi = {
        view.session_id: app.pane_reader(pane_id=view.pane_id, ansi=True)
        for view in snapshot.sessions
        if view.group == "needs-you" and view.pane_id
    }
    pane_text = {session_id: strip_ansi(text) for session_id, text in pane_ansi.items()}
    due = _slow_read_due(app=app)
    status_lines = _status_lines(app=app, sessions=snapshot.sessions, pane_ansi=pane_ansi, due=due)
    workspaces = _workspaces(app=app, sessions=snapshot.sessions, due=due)
    status = {view.session_id: view.status for view in snapshot.sessions}
    left_waiting: set[str] = set()
    for decision in app.store.all():
        now = status.get(decision.session_id, "gone")
        if decision.state == ANSWERED and _delivered(channel=decision.channel, status=now):
            app.store.mark_delivered(decision_id=decision.decision_id)
        if previous.get(decision.session_id) == "waiting" and now != "waiting":
            left_waiting.add(decision.session_id)
    for session_id in left_waiting:
        app.store.expire_for_session(session_id=session_id, created_before=previous_taken_at)
    previews = {
        view.session_id: preview
        for view in snapshot.sessions
        if view.status == "waiting"
        and (preview := app.preview_reader(session_id=view.session_id)) is not None
    }
    app.publish(
        snapshot=snapshot,
        pane_text=pane_text,
        previews=previews,
        status_lines=status_lines,
        workspaces=workspaces,
    )


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
            if app.auto_rename and not app.auto_renamed:
                app.auto_renamed = True
                rename_defaults(app=app)
        except Exception:
            log.exception("supervisor collector tick failed")
        stop.wait(interval)


def rename_defaults(*, app: SupervisorApp) -> list[Rename]:
    with app.changed:
        sessions, workspaces = list(app.snapshot.sessions), dict(app.workspaces)
    done = []
    for rename in plan_renames(sessions=sessions, workspaces=workspaces):
        try:
            app.renamer(
                pane_id=rename.session.pane_id,
                session_name=rename.session.name,
                name=rename.name,
                confirmed_by=AUTO_RENAMED_BY,
                log_path=app.log_path,
            )
        except ProbeError:
            log.warning("could not rename %s to %s", rename.session.name, rename.name)
            continue
        done.append(rename)
    return done


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
                "/api/session": self._session_detail,
                "/api/project": self._project_detail,
                "/lessons": self._lessons,
            }
        )

    def do_POST(self) -> None:
        self._dispatch(
            routes={
                "/decisions": self._post_decisions,
                "/decisions/answers": self._post_decision_answers,
                "/decisions/release": self._post_decision_release,
                "/settings": self._post_settings,
                "/answer": self._post_answer,
                "/keys": self._post_keys,
                "/reply": self._post_reply,
                "/introduce": self._post_introduce,
                "/rename": self._post_rename,
                "/command": self._post_command,
                "/launch": self._post_launch,
                "/preapprove": self._post_preapprove,
                "/lessons": self._post_lesson,
            }
        )

    def _dispatch(self, *, routes: dict[str, Callable[[dict[str, str]], None]]) -> None:
        url = urlsplit(self.path)
        handler = routes.get(url.path)
        try:
            if handler is None:
                raise RequestError(status=HTTPStatus.NOT_FOUND, message="no such route")
            query = {key: values[-1] for key, values in parse_qs(url.query).items()}
            self._check_token(params=query, path=url.path)
            handler(self._params(query=query))
        except RequestError as exc:
            self._json(status=exc.status, payload={"error": exc.message})
        except Exception:
            log.exception("supervisor request failed: %s %s", self.command, url.path)
            self._json(
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                payload={"error": "The supervisor hit an internal error; see its log."},
            )

    def _content_length(self) -> int:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST, message="bad Content-Length"
            ) from exc
        if length < 0:
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message="bad Content-Length")
        if length > MAX_BODY_BYTES:
            raise RequestError(
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, message="body too large"
            )
        return length

    def _params(self, *, query: dict[str, str]) -> dict[str, str]:
        params = dict(query)
        if self.command != "POST":
            return params
        length = self._content_length()
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

    def _check_token(self, *, params: dict[str, str], path: str) -> None:
        offered = (self.headers.get(TOKEN_HEADER) or params.get("token", "")).encode()
        accepted = [self.app.token]
        if path in HOOK_ROUTES and self.app.hook_token:
            accepted.append(self.app.hook_token)
        if not any(hmac.compare_digest(offered, token.encode()) for token in accepted):
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
        asked = [question for question in questions if isinstance(question, dict)]
        holdable = bool(body.get("hold")) and not any(
            question.get("multiSelect") for question in asked
        )
        wait = self.app.page_settings().answer_wait_seconds if holdable else 0
        added = self.app.store.add_from_hook(
            session_id=str(body["session_id"]),
            cwd=str(body.get("cwd", "")),
            questions=asked,
            hold_seconds=wait,
            now=self.app.now(),
        )
        self.app.nudge()
        self._json(
            status=HTTPStatus.CREATED,
            payload={
                "decision_ids": [decision.decision_id for decision in added],
                "wait_seconds": wait,
            },
        )

    def _decision_ids(self) -> list[str]:
        ids = self._body().get("decision_ids")
        if not isinstance(ids, list) or not ids:
            raise RequestError(status=HTTPStatus.BAD_REQUEST, message="decision_ids is required")
        return [str(item) for item in ids]

    def _post_decision_answers(self, params: dict[str, str]) -> None:
        answers = self.app.store.collect(decision_ids=self._decision_ids())
        if answers is not None:
            self.app.nudge()
        self._ok(answers=answers)

    def _post_decision_release(self, params: dict[str, str]) -> None:
        self.app.store.release(decision_ids=self._decision_ids())
        self.app.nudge()
        self._ok()

    def _post_settings(self, params: dict[str, str]) -> None:
        raw = self._body().get("answer_wait_seconds")
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST, message="answer_wait_seconds must be a whole number"
            )
        if self.app.settings is None:
            raise RequestError(
                status=HTTPStatus.SERVICE_UNAVAILABLE, message="This page keeps no settings."
            )
        saved = self.app.settings.save(settings=PageSettings(answer_wait_seconds=raw))
        self.app.nudge()
        self._ok(settings=asdict(saved))

    def _listed_session(self, *, session_id: str) -> SessionView:
        view = self.app.session(session_id=session_id)
        if view is None:
            raise RequestError(status=HTTPStatus.CONFLICT, message="That session is gone.")
        return view

    def _session_detail(self, params: dict[str, str]) -> None:
        view = self._listed_session(session_id=params.get("session_id", ""))
        tail = (
            self.app.pane_reader(pane_id=view.pane_id, lines=TAIL_LINES, source=TAIL_SOURCE)
            if view.pane_id and params.get("screen") == "1"
            else ""
        )
        preview = self.app.preview_reader(session_id=view.session_id)
        recent = self.app.recent_reader(session_id=view.session_id)
        conversation = self.app.conversation_reader(session_id=view.session_id)
        tasks = self.app.tasks_reader(session_id=view.session_id)
        self._json(
            status=HTTPStatus.OK,
            payload={
                "session_id": view.session_id,
                "conversation": [asdict(entry) for entry in conversation],
                "tasks": [asdict(task) for task in tasks],
                "tail": _excerpt(text=tail, lines=TAIL_LINES),
                "preview": asdict(preview) if preview else None,
                "recent": [asdict(tool) for tool in recent],
            },
        )

    def _post_answer(self, params: dict[str, str]) -> None:
        body = self._body()
        decision = self.app.store.get(decision_id=str(body.get("decision_id", "")))
        if decision is None or decision.state != OPEN:
            raise RequestError(status=HTTPStatus.CONFLICT, message="Already answered.")
        index = _option_index(raw=body.get("option_index"), decision=decision)
        answer = decision.options[index]
        if is_held(decision=decision, now=self.app.now()):
            self._answer_held(decision=decision, answer=answer)
            return
        view = self._listed_session(session_id=decision.session_id)
        by_keys = view.status == "waiting" and bool(view.pane_id)
        if by_keys:
            self._answer_by_keys(decision=decision, view=view, index=index, answer=answer)
        else:
            self._answer_by_relay(decision=decision, view=view, answer=answer)
        self.app.nudge()
        self._ok(channel="keys" if by_keys else "relay")

    def _answer_held(self, *, decision: Decision, answer: str) -> None:
        stored = self.app.store.answer(
            decision_id=decision.decision_id, answer=answer, channel=HOOK_CHANNEL
        )
        if stored is None:
            raise RequestError(status=HTTPStatus.CONFLICT, message="Already answered.")
        log_action(
            log_path=self.app.log_path,
            action="hook-answer",
            target=decision.session_id,
            detail=f"{decision.decision_id}: {answer}",
            confirmed_by=CONFIRMED_BY,
        )
        self.app.nudge()
        self._ok(channel=HOOK_CHANNEL)

    def _answer_by_keys(
        self,
        *,
        decision: Decision,
        view: SessionView,
        index: int,
        answer: str,
    ) -> None:
        live = parse_prompt(pane_text=self.app.pane_reader(pane_id=view.pane_id))
        if find_option(prompt=live, key=str(index + 1), label=answer) is None:
            raise RequestError(
                status=HTTPStatus.CONFLICT,
                message="The question on screen is not this one. Nothing was sent.",
            )
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
        try:
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
        except (InvalidMessageError, OSError) as exc:
            self.app.store.reopen(decision_id=decision.decision_id)
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc

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

    def _known_project(self, *, root: str) -> Project:
        with self.app.changed:
            roots = {workspace.root for workspace in self.app.workspaces.values()}
        if not root or root not in roots:
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST,
                message="Pick a project from the session list.",
            )
        try:
            return self.app.project_reader(root=root)
        except LaunchError as exc:
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc

    def _past(self, *, project: Project) -> list[PastSession]:
        with self.app.changed:
            running = {view.session_id for view in self.app.snapshot.sessions}
        return self.app.past_reader(
            checkouts=[checkout.path for checkout in project.checkouts], running=running
        )

    def _project_detail(self, params: dict[str, str]) -> None:
        project = self._known_project(root=params.get("root", ""))
        self._json(
            status=HTTPStatus.OK,
            payload={
                "root": project.root,
                "name": project.name,
                "checkouts": [
                    {
                        "path": checkout.path,
                        "branch": checkout.branch,
                        "is_main": checkout.is_main,
                        "open": bool(checkout.workspace_id)
                        or (checkout.is_main and bool(project.main_workspace_id)),
                    }
                    for checkout in project.checkouts
                ],
                "past": [asdict(past) for past in self._past(project=project)],
            },
        )

    def _launch(self, *, body: dict[str, Any], project: Project) -> Launched:
        action = str(body.get("action", ""))
        if action == "worktree":
            return self.app.worktree_maker(
                project=project, branch=str(body.get("branch", "")).strip()
            )
        if action == "session":
            return self.app.opener(project=project, path=str(body.get("path") or project.root))
        if action == "resume":
            session_id = str(body.get("session_id", ""))
            past = next(
                (item for item in self._past(project=project) if item.session_id == session_id),
                None,
            )
            if past is None:
                raise RequestError(
                    status=HTTPStatus.CONFLICT,
                    message="That session is running or no longer in this project.",
                )
            return self.app.opener(project=project, path=past.cwd, resume=past.session_id)
        raise RequestError(status=HTTPStatus.BAD_REQUEST, message=f"Unknown action {action!r}.")

    def _post_launch(self, params: dict[str, str]) -> None:
        body = self._body()
        project = self._known_project(root=str(body.get("root", "")))
        try:
            launched = self._launch(body=body, project=project)
        except LaunchError as exc:
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc
        log_action(
            log_path=self.app.log_path,
            action=f"launch-{body.get('action')}",
            target=launched.path or project.root,
            detail=f"{launched.agent} in {launched.pane_id}",
            confirmed_by=CONFIRMED_BY,
        )
        self._ok(pane_id=launched.pane_id, agent=launched.agent, path=launched.path)

    def _idle_pane(self, *, view: SessionView, what: str) -> str:
        if view.status != "idle" or not view.pane_id:
            raise RequestError(
                status=HTTPStatus.CONFLICT,
                message=f"{what} once the session is idle in a Herdr pane; "
                "it is busy or has no pane.",
            )
        return view.pane_id

    def _post_command(self, params: dict[str, str]) -> None:
        body = self._body()
        view = self._listed_session(session_id=str(body.get("session_id", "")))
        command = str(body.get("command", ""))
        if command not in SESSION_COMMANDS:
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST,
                message=f"Unknown command; use one of {', '.join(SESSION_COMMANDS)}.",
            )
        pane_id = self._idle_pane(view=view, what="Run it")
        try:
            self.app.commander(
                pane_id=pane_id,
                session_name=view.name,
                command=command,
                confirmed_by=CONFIRMED_BY,
                log_path=self.app.log_path,
            )
        except ProbeError as exc:
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc
        self._ok(sent=SESSION_COMMANDS[command])

    def _post_rename(self, params: dict[str, str]) -> None:
        body = self._body()
        view = self._listed_session(session_id=str(body.get("session_id", "")))
        name = str(body.get("name", "")).strip()
        if not is_valid_name(name=name):
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST,
                message=(
                    "Use letters, digits, '.', '_' or '-' (up to 64), "
                    "starting with a letter or digit."
                ),
            )
        pane_id = self._idle_pane(view=view, what="Rename")
        try:
            self.app.renamer(
                pane_id=pane_id,
                session_name=view.name,
                name=name,
                confirmed_by=CONFIRMED_BY,
                log_path=self.app.log_path,
            )
        except ProbeError as exc:
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc
        self._ok(name=name)

    def _peer(self, *, view: SessionView) -> Peer:
        with self.app.changed:
            workspace = self.app.workspaces.get(view.cwd)
            status_line = strip_ansi(self.app.status_lines.get(view.session_id, ""))
        link = _workspace_payload(workspace=workspace, cwd=view.cwd, status_line=status_line)
        return Peer(
            name=view.name,
            session_id=view.session_id,
            cwd=view.cwd,
            branch=link["branch"],
            issue=link["issue"],
            pr_url=link["pr_url"],
            summary=view.summary,
        )

    def _post_introduce(self, params: dict[str, str]) -> None:
        body = self._body()
        first = self._listed_session(session_id=str(body.get("session_id", "")))
        second = self._listed_session(session_id=str(body.get("peer_id", "")))
        if first.session_id == second.session_id:
            raise RequestError(
                status=HTTPStatus.BAD_REQUEST, message="Drop a different session to introduce."
            )
        request_id = f"{first.session_id[:8]}-{second.session_id[:8]}"
        try:
            introduce(
                bus_root=self.app.bus_root,
                relay_mailbox=self.app.relay_mailbox,
                first=self._peer(view=first),
                second=self._peer(view=second),
                request_id=request_id,
                confirmed_by=CONFIRMED_BY,
                log_path=self.app.log_path,
            )
        except (InvalidMessageError, OSError) as exc:
            raise RequestError(status=HTTPStatus.BAD_GATEWAY, message=str(exc)) from exc
        self._ok(request_id=request_id)

    def _post_preapprove(self, params: dict[str, str]) -> None:
        body = self._body()
        view = self._listed_session(session_id=str(body.get("session_id", "")))
        with self.app.changed:
            preview = self.app.previews.get(view.session_id)
        commands = self.app.commands_reader(session_id=view.session_id)
        chosen = str(body.get("command", "")).strip()
        if chosen:
            if chosen not in commands:
                raise RequestError(
                    status=HTTPStatus.CONFLICT,
                    message="That command is not among the session's recent commands.",
                )
            preview, commands = None, [chosen]
        if preview is None and not commands:
            raise RequestError(
                status=HTTPStatus.CONFLICT,
                message="Nothing to pre-approve: no pending call or commands in that session.",
            )
        request_id = f"{view.session_id[:8]}-{uuid4().hex[:6]}"
        request_preapproval(
            bus_root=self.app.bus_root,
            relay_mailbox=self.app.relay_mailbox,
            session_name=view.name,
            session_id=view.session_id,
            cwd=view.cwd,
            request_id=request_id,
            pending=asdict(preview) if preview else None,
            commands=commands,
            confirmed_by=CONFIRMED_BY,
            log_path=self.app.log_path,
        )
        self._ok(request_id=request_id, commands=len(commands))

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
