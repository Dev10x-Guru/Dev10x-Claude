from __future__ import annotations

import http.client
import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from dev10x.comm.overwatch import paths
from dev10x.core.hooks.base import load_hook_stdin

POST_TIMEOUT_SECONDS = 1.0
POLL_SECONDS = 1.0
HERDR_ENV_VAR = "HERDR_ENV"
ANSWERED_REASON = "Answered on the Overwatch page."

Opener = Callable[..., Any]


def _port() -> int:
    try:
        return int(os.environ.get(paths.PORT_ENV_VAR, paths.DEFAULT_PORT))
    except ValueError:
        return paths.DEFAULT_PORT


def _in_herdr() -> bool:
    return os.environ.get(HERDR_ENV_VAR) == "1"


def _emit(text: str) -> None:
    sys.stdout.write(text + "\n")


class _Daemon:
    def __init__(self, *, port: int, token: str, timeout: float, opener: Opener) -> None:
        self._base = f"http://127.0.0.1:{port}"
        self._token = token
        self._timeout = timeout
        self._opener = opener

    def post(self, *, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        request = urllib.request.Request(
            url=f"{self._base}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", paths.TOKEN_HEADER: self._token},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = json.loads(response.read() or b"{}")
        except (OSError, ValueError, http.client.HTTPException):
            return None
        return payload if isinstance(payload, dict) else None


def _wait_for_answers(
    *,
    daemon: _Daemon,
    decision_ids: list[str],
    wait_seconds: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> dict[str, str] | None:
    deadline = clock() + wait_seconds
    while clock() < deadline:
        sleep(POLL_SECONDS)
        reply = daemon.post(path="/decisions/answers", body={"decision_ids": decision_ids})
        answers = reply.get("answers") if reply else None
        if isinstance(answers, dict) and answers:
            return {str(question): str(answer) for question, answer in answers.items()}
    daemon.post(path="/decisions/release", body={"decision_ids": decision_ids})
    return None


def _answered(*, tool_input: dict[str, Any], answers: dict[str, str]) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": ANSWERED_REASON,
                "updatedInput": {**tool_input, "answers": answers},
            }
        }
    )


def overwatch_decision(
    data: dict | None = None,
    *,
    port: int | None = None,
    timeout: float = POST_TIMEOUT_SECONDS,
    opener: Opener = urllib.request.urlopen,
    in_herdr: Callable[[], bool] = _in_herdr,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = _emit,
) -> None:
    payload = data if data is not None else load_hook_stdin()
    if not isinstance(payload, dict):
        return
    tool_input = payload.get("tool_input")
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    if not payload.get("session_id") or not isinstance(questions, list) or not questions:
        return
    try:
        token = paths.token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return
    daemon = _Daemon(port=port or _port(), token=token, timeout=timeout, opener=opener)
    reply = daemon.post(
        path="/decisions",
        body={
            "session_id": payload["session_id"],
            "cwd": payload.get("cwd", ""),
            "questions": questions,
            "hold": not in_herdr(),
        },
    )
    if not reply:
        return
    decision_ids = [str(item) for item in reply.get("decision_ids") or []]
    wait_seconds = reply.get("wait_seconds") or 0
    if not decision_ids or not isinstance(wait_seconds, int | float) or wait_seconds <= 0:
        return
    answers = _wait_for_answers(
        daemon=daemon,
        decision_ids=decision_ids,
        wait_seconds=wait_seconds,
        clock=clock,
        sleep=sleep,
    )
    if answers is not None and isinstance(tool_input, dict):
        emit(_answered(tool_input=tool_input, answers=answers))
