from __future__ import annotations

import difflib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir

TAIL_BYTES = 512 * 1024
MAX_PREVIEW_LINES = 400
MAX_FILE_BYTES = 256 * 1024
DIFF_TOOLS = ("Edit", "MultiEdit", "Write")
MAX_COMMANDS = 60
MAX_RECENT_TOOLS = 60
MAX_CONVERSATION_ENTRIES = 120
MAX_ENTRY_CHARS = 6000
MAX_RESULT_CHARS = 400
REJECTED_MARKERS = ("doesn't want to proceed", "was rejected", "Permission to use")


@dataclass(frozen=True)
class PendingTool:
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class RecentTool:
    tool: str
    target: str
    outcome: str
    command: str = ""
    decided_by: str = ""


@dataclass
class ConversationEntry:
    role: str
    kind: str
    text: str
    at: str = ""
    tool: str = ""
    outcome: str = ""
    result: str = ""


@dataclass(frozen=True)
class Preview:
    tool: str
    title: str
    kind: str
    body: str
    truncated: bool = False


def find_transcript(*, session_id: str, projects_root: Path | None = None) -> Path | None:
    root = projects_root if projects_root is not None else ClaudeDir.projects_dir()
    return next(iter(sorted(root.glob(f"*/{session_id}.jsonl"))), None)


def _tail_lines(*, path: Path) -> list[str]:
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - TAIL_BYTES))
        chunk = handle.read()
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if size > TAIL_BYTES else lines


def _content(*, record: dict[str, Any]) -> list[dict[str, Any]]:
    content = (record.get("message") or {}).get("content")
    return (
        [item for item in content if isinstance(item, dict)] if isinstance(content, list) else []
    )


def _records(*, path: Path) -> Iterator[dict[str, Any]]:
    for line in _tail_lines(path=path):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def _items(*, path: Path) -> Iterator[dict[str, Any]]:
    for record in _records(path=path):
        yield from _content(record=record)


def _tool(*, item: dict[str, Any]) -> PendingTool:
    tool_input = item.get("input")
    return PendingTool(
        name=str(item.get("name", "")),
        input=tool_input if isinstance(tool_input, dict) else {},
    )


def read_pending_tool(*, path: Path) -> PendingTool | None:
    pending: dict[str, PendingTool] = {}
    order: list[str] = []
    for item in _items(path=path):
        if item.get("type") == "tool_use" and item.get("id"):
            pending[item["id"]] = _tool(item=item)
            order.append(item["id"])
        elif item.get("type") == "tool_result":
            pending.pop(str(item.get("tool_use_id")), None)
    open_ids = [tool_id for tool_id in order if tool_id in pending]
    return pending[open_ids[-1]] if open_ids else None


def read_session_commands(
    *,
    session_id: str,
    projects_root: Path | None = None,
    limit: int = MAX_COMMANDS,
) -> list[str]:
    path = find_transcript(session_id=session_id, projects_root=projects_root)
    if path is None:
        return []
    commands: list[str] = []
    try:
        for item in _items(path=path):
            if item.get("type") != "tool_use" or item.get("name") != "Bash":
                continue
            command = str(_tool(item=item).input.get("command", "")).strip()
            if command and command not in commands:
                commands.append(command)
    except OSError:
        return []
    return commands[-limit:]


def _target(*, tool: PendingTool) -> str:
    for key in ("command", "file_path", "url", "pattern", "path"):
        value = str(tool.input.get(key, "")).strip()
        if value:
            return value
    return ""


def _outcome(*, result: dict[str, Any] | None) -> str:
    if result is None:
        return "pending"
    content = result.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    if result.get("is_error") and any(marker in text for marker in REJECTED_MARKERS):
        return "rejected"
    return "failed" if result.get("is_error") else "ran"


def read_recent_tools(
    *,
    session_id: str,
    projects_root: Path | None = None,
    limit: int = MAX_RECENT_TOOLS,
) -> list[RecentTool]:
    path = find_transcript(session_id=session_id, projects_root=projects_root)
    if path is None:
        return []
    calls: dict[str, PendingTool] = {}
    results: dict[str, dict[str, Any]] = {}
    decided_by: dict[str, str] = {}
    try:
        for record in _records(path=path):
            decision = record.get("permissionDecision")
            for item in _content(record=record):
                if item.get("type") == "tool_use" and item.get("id"):
                    calls[str(item["id"])] = _tool(item=item)
                elif item.get("type") == "tool_result":
                    tool_id = str(item.get("tool_use_id"))
                    results[tool_id] = item
                    if isinstance(decision, dict):
                        decided_by[tool_id] = str(decision.get("source", ""))
    except OSError:
        return []
    recent = [
        RecentTool(
            tool=tool.name,
            target=_target(tool=tool),
            outcome=_outcome(result=results.get(tool_id)),
            command=str(tool.input.get("command", "")).strip() if tool.name == "Bash" else "",
            decided_by=decided_by.get(tool_id, ""),
        )
        for tool_id, tool in calls.items()
    ]
    return list(reversed(recent[-limit:]))


def _clip(*, text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}…"


def _result_text(*, item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _said(*, record: dict[str, Any]) -> list[str]:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return [content]
    return [
        str(item.get("text", "")) for item in _content(record=record) if item.get("type") == "text"
    ]


def read_conversation(
    *,
    session_id: str,
    projects_root: Path | None = None,
    limit: int = MAX_CONVERSATION_ENTRIES,
) -> list[ConversationEntry]:
    path = find_transcript(session_id=session_id, projects_root=projects_root)
    if path is None:
        return []
    entries: list[ConversationEntry] = []
    calls: dict[str, ConversationEntry] = {}
    try:
        for record in _records(path=path):
            role, at = record.get("type"), str(record.get("timestamp", ""))
            if role not in ("user", "assistant") or record.get("isMeta"):
                continue
            for text in _said(record=record):
                if text.strip() and not text.lstrip().startswith("<"):
                    entries.append(
                        ConversationEntry(
                            role=str(role),
                            kind="text",
                            text=_clip(text=text, limit=MAX_ENTRY_CHARS),
                            at=at,
                        )
                    )
            for item in _content(record=record):
                if item.get("type") == "tool_use" and item.get("id"):
                    tool = _tool(item=item)
                    entry = ConversationEntry(
                        role="assistant",
                        kind="tool",
                        text=_clip(text=_target(tool=tool), limit=MAX_ENTRY_CHARS),
                        at=at,
                        tool=tool.name,
                        outcome="pending",
                    )
                    calls[str(item["id"])] = entry
                    entries.append(entry)
                elif item.get("type") == "tool_result":
                    call = calls.get(str(item.get("tool_use_id")))
                    if call is not None:
                        call.outcome = _outcome(result=item)
                        call.result = _clip(text=_result_text(item=item), limit=MAX_RESULT_CHARS)
    except OSError:
        return []
    return entries[-limit:]


def _diff(*, path: str, before: str, after: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )


def _current_text(*, path: str) -> str:
    target = Path(path)
    try:
        if target.stat().st_size > MAX_FILE_BYTES:
            return ""
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _diff_body(*, tool: PendingTool) -> str:
    path = str(tool.input.get("file_path", ""))
    if tool.name == "Write":
        return _diff(
            path=path, before=_current_text(path=path), after=str(tool.input.get("content", ""))
        )
    edits = tool.input.get("edits") if tool.name == "MultiEdit" else [tool.input]
    return "\n".join(
        _diff(
            path=path,
            before=str(edit.get("old_string", "")),
            after=str(edit.get("new_string", "")),
        )
        for edit in edits or []
        if isinstance(edit, dict)
    )


def _cap(*, body: str) -> tuple[str, bool]:
    lines = body.splitlines()
    if len(lines) <= MAX_PREVIEW_LINES:
        return body, False
    return "\n".join(lines[:MAX_PREVIEW_LINES]), True


def build_preview(*, tool: PendingTool) -> Preview:
    if tool.name in DIFF_TOOLS:
        kind, title, body = "diff", str(tool.input.get("file_path", "")), _diff_body(tool=tool)
    elif tool.name == "Bash":
        kind = "command"
        title = str(tool.input.get("description", ""))
        body = str(tool.input.get("command", ""))
    else:
        kind, title, body = "text", "", json.dumps(tool.input, indent=2, ensure_ascii=False)
    capped, truncated = _cap(body=body)
    return Preview(tool=tool.name, title=title, kind=kind, body=capped, truncated=truncated)


def read_preview(*, session_id: str, projects_root: Path | None = None) -> Preview | None:
    path = find_transcript(session_id=session_id, projects_root=projects_root)
    if path is None:
        return None
    try:
        tool = read_pending_tool(path=path)
    except OSError:
        return None
    return build_preview(tool=tool) if tool else None
