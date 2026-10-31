from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from typing import Any

from dev10x.comm.supervisor import paths
from dev10x.core.hooks.base import load_hook_stdin

POST_TIMEOUT_SECONDS = 1.0

Opener = Callable[..., Any]


def _port() -> int:
    try:
        return int(os.environ.get(paths.PORT_ENV_VAR, paths.DEFAULT_PORT))
    except ValueError:
        return paths.DEFAULT_PORT


def supervisor_decision(
    data: dict | None = None,
    *,
    port: int | None = None,
    timeout: float = POST_TIMEOUT_SECONDS,
    opener: Opener = urllib.request.urlopen,
) -> None:
    payload = data if data is not None else load_hook_stdin()
    questions = (payload.get("tool_input") or {}).get("questions")
    if not payload.get("session_id") or not isinstance(questions, list) or not questions:
        return
    try:
        token = paths.token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return
    request = urllib.request.Request(
        url=f"http://127.0.0.1:{port or _port()}/decisions",
        data=json.dumps(
            {
                "session_id": payload["session_id"],
                "cwd": payload.get("cwd", ""),
                "questions": questions,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", paths.TOKEN_HEADER: token},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout):
            pass
    except (OSError, ValueError):
        return
