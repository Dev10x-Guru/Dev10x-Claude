"""Artifact documents shown on the Overwatch page (GH-1938, ADR-0036)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.file_locks import atomic_append_line, file_lock, locked_json_update

log = logging.getLogger(__name__)

SCHEMA = "dev10x.artifact/v1"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MAX_DOCUMENT_BYTES = 512 * 1024
RECENT_EVENTS = 20
TONES = ("ok", "warn", "bad", "info")
BUTTON_TONES = ("primary", "danger", "default")
FIELD_KINDS = ("text", "textarea", "select")
CONTROL_TYPES = ("button", "choice", "form")
STORE_FIELDS = ("revision", "updated_at", "owner", "shares")
CONTROL_EVENT = "control"
SHARE_EVENT = "share"


def _local_now() -> datetime:
    return datetime.now().astimezone()


def new_event_id() -> str:
    return uuid4().hex[:12]


class _Invalid(ValueError):
    pass


def _fail(*, path: str, message: str) -> _Invalid:
    return _Invalid(f"{path}: {message}")


def _mapping(*, value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(path=path, message="must be an object")
    return value


def _text(*, owner: dict[str, Any], key: str, path: str, required: bool = True) -> str:
    value = owner.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise _fail(path=f"{path}.{key}", message="must be a non-empty string")
    return value


def _choice(*, owner: dict[str, Any], key: str, path: str, allowed: tuple[str, ...]) -> None:
    value = owner.get(key)
    if value not in allowed:
        raise _fail(path=f"{path}.{key}", message=f"must be one of {', '.join(allowed)}")


def _slug(*, owner: dict[str, Any], key: str, path: str) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise _fail(
            path=f"{path}.{key}",
            message="must be a slug: lowercase letters, digits and '-', up to 64",
        )
    return value


def _list(
    *,
    owner: dict[str, Any],
    key: str,
    path: str,
    min_items: int = 0,
) -> list[Any]:
    value = owner.get(key)
    if not isinstance(value, list):
        raise _fail(path=f"{path}.{key}", message="must be a list")
    if len(value) < min_items:
        raise _fail(path=f"{path}.{key}", message=f"needs at least {min_items} item(s)")
    return value


def _strings(*, owner: dict[str, Any], key: str, path: str, min_items: int = 0) -> list[str]:
    items = _list(owner=owner, key=key, path=path, min_items=min_items)
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise _fail(path=f"{path}.{key}[{index}]", message="must be a string")
    return items


def _objects(
    *,
    owner: dict[str, Any],
    key: str,
    path: str,
    min_items: int = 0,
) -> list[tuple[str, dict[str, Any]]]:
    items = _list(owner=owner, key=key, path=path, min_items=min_items)
    return [
        (f"{path}.{key}[{index}]", _mapping(value=item, path=f"{path}.{key}[{index}]"))
        for index, item in enumerate(items)
    ]


def _claim(*, block: dict[str, Any], path: str) -> None:
    _text(owner=block, key="text", path=path)


def _prose(*, block: dict[str, Any], path: str) -> None:
    _strings(owner=block, key="paragraphs", path=path, min_items=1)


def _callout(*, block: dict[str, Any], path: str) -> None:
    _choice(owner=block, key="tone", path=path, allowed=TONES)
    _text(owner=block, key="text", path=path)


def _kv(*, block: dict[str, Any], path: str) -> None:
    for item_path, item in _objects(owner=block, key="items", path=path):
        _text(owner=item, key="key", path=item_path)
        _text(owner=item, key="value", path=item_path, required=False)


def _cell(*, value: object, path: str) -> None:
    if isinstance(value, str):
        return
    cell = _mapping(value=value, path=path)
    _text(owner=cell, key="text", path=path, required=False)
    if "tone" in cell:
        _choice(owner=cell, key="tone", path=path, allowed=TONES)


def _table(*, block: dict[str, Any], path: str) -> None:
    _strings(owner=block, key="columns", path=path, min_items=1)
    for row_index, row in enumerate(_list(owner=block, key="rows", path=path)):
        row_path = f"{path}.rows[{row_index}]"
        if not isinstance(row, list):
            raise _fail(path=row_path, message="must be a list of cells")
        for cell_index, cell in enumerate(row):
            _cell(value=cell, path=f"{row_path}[{cell_index}]")


def _pills(*, block: dict[str, Any], path: str) -> None:
    for item_path, item in _objects(owner=block, key="items", path=path):
        _text(owner=item, key="text", path=item_path)
        _choice(owner=item, key="tone", path=item_path, allowed=TONES)


def _stats(*, block: dict[str, Any], path: str) -> None:
    for item_path, item in _objects(owner=block, key="items", path=path):
        _text(owner=item, key="label", path=item_path)
        _text(owner=item, key="value", path=item_path)
        _text(owner=item, key="note", path=item_path, required=False)


def _mermaid(*, block: dict[str, Any], path: str) -> None:
    _text(owner=block, key="source", path=path)


def _draft(*, block: dict[str, Any], path: str) -> None:
    _text(owner=block, key="label", path=path)
    _text(owner=block, key="text", path=path)


def _evidence(*, block: dict[str, Any], path: str) -> None:
    for item_path, item in _objects(owner=block, key="items", path=path):
        _text(owner=item, key="claim", path=item_path)
        _text(owner=item, key="ref", path=item_path)
        _text(owner=item, key="check", path=item_path, required=False)


def _decisions(*, block: dict[str, Any], path: str) -> None:
    for item_path, item in _objects(owner=block, key="items", path=path):
        _text(owner=item, key="question", path=item_path)
        _text(owner=item, key="owner", path=item_path, required=False)
        _text(owner=item, key="control", path=item_path, required=False)


def _button(*, block: dict[str, Any], path: str) -> None:
    _text(owner=block, key="label", path=path)
    if "tone" in block:
        _choice(owner=block, key="tone", path=path, allowed=BUTTON_TONES)
    _text(owner=block, key="value", path=path, required=False)


def _multi(*, block: dict[str, Any], path: str) -> None:
    if "multi" in block and not isinstance(block["multi"], bool):
        raise _fail(path=f"{path}.multi", message="must be true or false")


def _choice_control(*, block: dict[str, Any], path: str) -> None:
    _text(owner=block, key="label", path=path)
    _strings(owner=block, key="options", path=path, min_items=2)
    _multi(block=block, path=path)


def _form(*, block: dict[str, Any], path: str) -> None:
    _text(owner=block, key="label", path=path)
    _text(owner=block, key="submit", path=path, required=False)
    names: set[str] = set()
    for field_path, field in _objects(owner=block, key="fields", path=path, min_items=1):
        name = _text(owner=field, key="name", path=field_path)
        if name in names:
            raise _fail(path=f"{field_path}.name", message=f'duplicate field name "{name}"')
        names.add(name)
        _text(owner=field, key="label", path=field_path)
        _choice(owner=field, key="kind", path=field_path, allowed=FIELD_KINDS)
        if field["kind"] == "select":
            _strings(owner=field, key="options", path=field_path, min_items=1)


BLOCKS: dict[str, Callable[..., None]] = {
    "claim": _claim,
    "prose": _prose,
    "callout": _callout,
    "kv": _kv,
    "table": _table,
    "pills": _pills,
    "stats": _stats,
    "mermaid": _mermaid,
    "draft": _draft,
    "evidence": _evidence,
    "decisions": _decisions,
    "button": _button,
    "choice": _choice_control,
    "form": _form,
}


def _meta(*, document: dict[str, Any]) -> None:
    if "meta" not in document:
        return
    meta = _mapping(value=document["meta"], path="meta")
    for key, value in meta.items():
        if not isinstance(value, str):
            raise _fail(path=f"meta.{key}", message="must be a string")


def _views(*, document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    view_ids: set[str] = set()
    controls: dict[str, dict[str, Any]] = {}
    links: list[tuple[str, str]] = []
    for view_path, view in _objects(owner=document, key="views", path="document", min_items=1):
        view_path = view_path.removeprefix("document.")
        view_id = _slug(owner=view, key="id", path=view_path)
        if view_id in view_ids:
            raise _fail(path=f"{view_path}.id", message=f'duplicate view id "{view_id}"')
        view_ids.add(view_id)
        _text(owner=view, key="label", path=view_path)
        _text(owner=view, key="group", path=view_path, required=False)
        _text(owner=view, key="badge", path=view_path, required=False)
        for block_path, block in _objects(owner=view, key="blocks", path=view_path):
            kind = block.get("type")
            check = BLOCKS.get(kind) if isinstance(kind, str) else None
            if check is None:
                raise _fail(path=f"{block_path}.type", message=f'unknown block type "{kind}"')
            check(block=block, path=block_path)
            if kind in CONTROL_TYPES:
                control_id = _slug(owner=block, key="id", path=block_path)
                if control_id in controls:
                    raise _fail(
                        path=f"{block_path}.id", message=f'duplicate control id "{control_id}"'
                    )
                controls[control_id] = block
            if kind == "decisions":
                links.extend(
                    (f"{block_path}.items[{index}].control", item["control"])
                    for index, item in enumerate(block["items"])
                    if item.get("control")
                )
    for link_path, control_id in links:
        if control_id not in controls:
            raise _fail(path=link_path, message=f'no control with id "{control_id}"')
    return controls


def validate_document(*, document: object) -> Result[dict[str, Any]]:
    try:
        checked = _mapping(value=document, path="document")
        size = len(json.dumps(checked, ensure_ascii=False).encode("utf-8"))
        if size > MAX_DOCUMENT_BYTES:
            raise _fail(
                path="document",
                message=f"is {size} bytes; the limit is {MAX_DOCUMENT_BYTES // 1024} KiB",
            )
        if checked.get("schema") != SCHEMA:
            raise _fail(path="schema", message=f'must be "{SCHEMA}"')
        _slug(owner=checked, key="id", path="document")
        _text(owner=checked, key="title", path="document")
        _text(owner=checked, key="description", path="document", required=False)
        _meta(document=checked)
        _views(document=checked)
    except _Invalid as exc:
        return err(str(exc).removeprefix("document."))
    return ok({key: value for key, value in checked.items() if key not in STORE_FIELDS})


def find_control(*, document: dict[str, Any], control_id: str) -> dict[str, Any] | None:
    for view in document.get("views", []):
        for block in view.get("blocks", []):
            if block.get("type") in CONTROL_TYPES and block.get("id") == control_id:
                return block
    return None


def check_value(*, control: dict[str, Any], value: object) -> Result[object]:
    kind = control["type"]
    if kind == "button":
        return ok(value) if isinstance(value, str) else err("A button sends a string.")
    if kind == "choice":
        return _choice_value(control=control, value=value)
    return _form_value(control=control, value=value)


def _choice_value(*, control: dict[str, Any], value: object) -> Result[object]:
    multi = bool(control.get("multi"))
    if multi and not isinstance(value, list):
        return err("This choice takes a list of options.")
    picked = value if isinstance(value, list) and multi else [value]
    if not all(isinstance(item, str) and item in control["options"] for item in picked):
        return err("Pick from the listed options.")
    return ok(value)


def _form_value(*, control: dict[str, Any], value: object) -> Result[object]:
    names = {field["name"] for field in control["fields"]}
    if not isinstance(value, dict):
        return err("A form sends an object of field values.")
    if set(value) - names or not all(isinstance(item, str) for item in value.values()):
        return err("A form sends only its own fields, each as a string.")
    for field in control["fields"]:
        if field["kind"] == "select" and value.get(field["name"], "") not in [
            "",
            *field.get("options", []),
        ]:
            return err(f"Pick {field['name']} from its listed options.")
    return ok(value)


@dataclass(frozen=True)
class ArtifactSummary:
    id: str
    title: str
    owner: dict[str, str]
    revision: int
    updated_at: str


class ArtifactStore:
    def __init__(self, *, root: Path, now: Callable[[], datetime] = _local_now) -> None:
        self.root = root
        self._now = now

    def document_path(self, *, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}.json"

    def events_path(self, *, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}.events.jsonl"

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def put(self, *, document: object, owner: dict[str, str]) -> Result[dict[str, Any]]:
        checked = validate_document(document=document)
        if isinstance(checked, ErrorResult):
            return checked
        fresh = checked.value
        target = self.document_path(artifact_id=fresh["id"])
        try:
            with locked_json_update(target) as stored:
                saved = {
                    **fresh,
                    "revision": int(stored.get("revision", 0)) + 1,
                    "updated_at": self._stamp(),
                    "owner": owner,
                    "shares": list(stored.get("shares", [])),
                }
                stored.clear()
                stored.update(saved)
        except (OSError, ValueError, TypeError) as exc:
            return err(f"Could not write {target}: {exc}")
        return ok(saved)

    def get(self, *, artifact_id: str) -> dict[str, Any] | None:
        if not SLUG.fullmatch(artifact_id):
            return None
        target = self.document_path(artifact_id=artifact_id)
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("overwatch artifact %s is unreadable: %s", target, exc)
            return None
        return document if isinstance(document, dict) else None

    def index(self) -> list[ArtifactSummary]:
        found = []
        for target in sorted(self.root.glob("*.json")):
            document = self.get(artifact_id=target.stem)
            if document is None:
                continue
            owner = document.get("owner") or {}
            found.append(
                ArtifactSummary(
                    id=str(document.get("id", target.stem)),
                    title=str(document.get("title", "")),
                    owner={
                        "session_id": str(owner.get("session_id", "")),
                        "name": str(owner.get("name", "")),
                    },
                    revision=int(document.get("revision", 0)),
                    updated_at=str(document.get("updated_at", "")),
                )
            )
        return sorted(found, key=lambda summary: summary.updated_at, reverse=True)

    def add_share(
        self,
        *,
        artifact_id: str,
        publisher: str,
        url: str,
    ) -> Result[dict[str, Any]]:
        if self.get(artifact_id=artifact_id) is None:
            return err(f'No artifact "{artifact_id}".')
        target = self.document_path(artifact_id=artifact_id)
        try:
            with locked_json_update(target) as stored:
                stored["shares"] = [
                    *stored.get("shares", []),
                    {"publisher": publisher, "url": url, "at": self._stamp()},
                ]
                stored["revision"] = int(stored.get("revision", 0)) + 1
                stored["updated_at"] = self._stamp()
                saved = dict(stored)
        except (OSError, ValueError, TypeError) as exc:
            return err(f"Could not write {target}: {exc}")
        return ok(saved)

    def events(self, *, artifact_id: str) -> list[dict[str, Any]]:
        try:
            lines = self.events_path(artifact_id=artifact_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        found = []
        for number, line in enumerate(lines.splitlines(), start=1):
            try:
                event = json.loads(line)
            except ValueError:
                log.warning(
                    "overwatch artifact %s event log line %d is unreadable; skipped",
                    artifact_id,
                    number,
                )
                continue
            if isinstance(event, dict):
                found.append(event)
        return found

    def recent_events(
        self,
        *,
        artifact_id: str,
        limit: int = RECENT_EVENTS,
    ) -> list[dict[str, Any]]:
        return self.events(artifact_id=artifact_id)[-limit:]

    def already_sent(self, *, artifact_id: str, revision: int, control_id: str) -> bool:
        return any(
            event.get("kind") == CONTROL_EVENT
            and event.get("revision") == revision
            and event.get("control_id") == control_id
            for event in self.events(artifact_id=artifact_id)
        )

    def append_event(
        self,
        *,
        event_id: str,
        artifact_id: str,
        kind: str,
        revision: int,
        channel: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "event_id": event_id,
            "at": self._stamp(),
            "kind": kind,
            "artifact_id": artifact_id,
            "revision": revision,
            "channel": channel,
            **detail,
        }
        target = self.events_path(artifact_id=artifact_id)
        with file_lock(target):
            atomic_append_line(target, json.dumps(event, ensure_ascii=False))
        return event
