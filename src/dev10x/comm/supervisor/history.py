from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir

HEAD_BYTES = 64 * 1024
TAIL_BYTES = 256 * 1024
MAX_PAST_SESSIONS = 30
TOPIC_CHARS = 90
FOLDER_CHARS = re.compile(r"[/.]")
COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)


@dataclass(frozen=True)
class PastSession:
    session_id: str
    cwd: str
    title: str
    topic: str
    active_at: str
    named: bool


def transcript_folder(*, cwd: str) -> str:
    return FOLDER_CHARS.sub("-", cwd)


def _records(*, chunk: bytes) -> list[dict[str, Any]]:
    records = []
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _ends(*, path: Path) -> tuple[bytes, bytes]:
    with path.open("rb") as handle:
        head = handle.read(HEAD_BYTES)
        size = handle.seek(0, 2)
        handle.seek(max(0, size - TAIL_BYTES))
        return head, handle.read()


def _clip(*, text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= TOPIC_CHARS else f"{line[:TOPIC_CHARS].rstrip()}…"


def _command(*, text: str) -> str:
    name = COMMAND_NAME.search(text)
    if name is None:
        return ""
    args = COMMAND_ARGS.search(text)
    return f"{name.group(1).strip()} {args.group(1).strip() if args else ''}".strip()


def _first_prompt(*, records: list[dict[str, Any]]) -> str:
    first_command = ""
    for record in records:
        if record.get("type") != "user" or record.get("isMeta"):
            continue
        content = (record.get("message") or {}).get("content")
        text = content if isinstance(content, str) else ""
        if not text.strip():
            continue
        if not text.lstrip().startswith("<"):
            return _clip(text=text)
        first_command = first_command or _command(text=text)
    return _clip(text=first_command)


def _title(*, records: list[dict[str, Any]]) -> str:
    titles = [
        str(record.get("customTitle", ""))
        for record in records
        if record.get("type") == "custom-title" and record.get("customTitle")
    ]
    return titles[-1] if titles else ""


def read_past_session(*, path: Path, cwd: str) -> PastSession | None:
    try:
        head, tail = _ends(path=path)
        modified = path.stat().st_mtime
    except OSError:
        return None
    title = _title(records=_records(chunk=tail)) or _title(records=_records(chunk=head))
    return PastSession(
        session_id=path.stem,
        cwd=cwd,
        title=title,
        topic=_first_prompt(records=_records(chunk=head)),
        active_at=datetime.fromtimestamp(modified).astimezone().isoformat(timespec="seconds"),
        named=bool(title),
    )


def read_past_sessions(
    *,
    checkouts: list[str],
    running: set[str],
    projects_root: Path | None = None,
    limit: int = MAX_PAST_SESSIONS,
) -> list[PastSession]:
    root = projects_root if projects_root is not None else ClaudeDir.projects_dir()
    found = []
    for cwd in checkouts:
        for path in (root / transcript_folder(cwd=cwd)).glob("*.jsonl"):
            if path.stem in running:
                continue
            past = read_past_session(path=path, cwd=cwd)
            if past is not None:
                found.append(past)
    found.sort(key=lambda past: past.active_at, reverse=True)
    found.sort(key=lambda past: not past.named)
    return found[:limit]
