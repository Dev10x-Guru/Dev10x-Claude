"""One row per harvested source in a central hub note (GH-1985).

A daily note answers "what did I learn that day"; it cannot answer
"which of the things I saved travelled, and what shape do they share".
The hub keeps one row per source, keyed by its canonical URL, so a
re-fetch refreshes the row instead of adding a duplicate.

Reach numbers are a snapshot taken on the save date and never update
themselves. The ``Structure`` column (the beat chain the source
performs) is the part that compounds across rows.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from dev10x.core.domain.common.result import Result, SuccessResult, err, ok
from dev10x.core.domain.dev10x_paths import Dev10xConfigDir
from dev10x.core.domain.file_locks import LockTimeoutError, atomic_write_text, file_lock
from dev10x.kb.config import KbConfig
from dev10x.kb.links import relative_link
from dev10x.kb.persist import inside_vault
from dev10x.kb.record import SourceKind, read_meta

log = logging.getLogger(__name__)


class HubAction(StrEnum):
    CREATED = "created"
    APPENDED = "appended"
    REFRESHED = "refreshed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class HubWrite:
    path: Path | None
    action: HubAction
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path) if self.path else None,
            "action": self.action.value,
            "reason": self.reason,
        }


HEADER = "| Saved | Kind | Author | Title | Structure | Reach | Note |"
DIVIDER = "|---|---|---|---|---|---|---|"
INTRO = """# Harvested sources

One row per source saved with `dev10x-kb:lesson-harvest`. Reach numbers
are a **snapshot on the save date** and do not update themselves, so an
old row understates a source that kept growing.

`Structure` records the beat pattern the source performs — the
reusable part. Reuse labels from the vocabulary below before coining
one; a label used once records nothing.
"""
VOCABULARY = "## Structure vocabulary\n"


_URL_ESCAPES = {" ": "%20", "(": "%28", ")": "%29", "<": "%3C", ">": "%3E", "|": "%7C"}
_TITLE_CELL = 3


def link_url(url: str) -> str:
    """A URL that cannot end a Markdown link early."""
    return "".join(_URL_ESCAPES.get(char, char) for char in url)


def _cell(text: str) -> str:
    """One table cell: whitespace collapsed, backslash and pipe escaped."""
    return " ".join(text.split()).replace("\\", "\\\\").replace("|", "\\|")


@dataclass(frozen=True)
class HubRow:
    url: str
    cells: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"]({self.url})"

    def render(self) -> str:
        return "| " + " | ".join(self.cells) + " |"


def _title_cell(line: str) -> str:
    parts = line.split(" | ")
    return parts[_TITLE_CELL] if len(parts) > _TITLE_CELL else ""


def _count(raw: str) -> str:
    if not raw.isdigit() or int(raw) == 0:
        return "—"
    number = int(raw)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}k"
    return str(number)


def _age_days(*, published: str, measured: str) -> int:
    try:
        start = datetime.strptime(published[:8], "%Y%m%d").date()
        end = date.fromisoformat(measured)
    except ValueError:
        return 1
    return max((end - start).days, 1)


def reach(meta: dict[str, str]) -> str:
    """The comparable reach signal for the source's kind."""
    kind = meta.get("kind", "")
    if kind == SourceKind.YOUTUBE.value:
        views = meta.get("views", "")
        days = _age_days(published=meta.get("published", ""), measured=meta.get("measured_at", ""))
        per_day = str(int(views) // days) if views.isdigit() else ""
        likes = meta.get("likes", "")
        engagement = (
            f"{100 * int(likes) / int(views):.1f}% eng"
            if views.isdigit() and likes.isdigit() and int(views) > 0
            else "— eng"
        )
        return (
            f"{_count(views)} views · {_count(per_day)}/day · {engagement} · "
            f"{_count(meta.get('channel_subs', ''))} subs · {days} d"
        )
    if kind == SourceKind.SPOTIFY.value:
        return " · ".join(
            part for part in (meta.get("duration", ""), meta.get("show", "")) if part
        )
    words = meta.get("words", "")
    return " · ".join(
        part for part in (meta.get("site", ""), f"{words} words" if words else "") if part
    )


def build_row(*, meta: dict[str, str], name: str, structure: str, note_link: str) -> HubRow:
    speaker, separator, title = name.partition(" - ")
    author = speaker if separator else meta.get("author", "")
    url = link_url(meta.get("url", ""))
    label = _cell(title if separator else name).replace("[", "\\[").replace("]", "\\]")
    return HubRow(
        url=url,
        cells=(
            _cell(meta.get("measured_at", "")),
            _cell(meta.get("kind", "")),
            _cell(author),
            f"[{label}]({url})",
            _cell(structure),
            _cell(reach(meta)),
            note_link,
        ),
    )


def _frontmatter(now: str) -> str:
    return (
        "---\n"
        "type: Hub\n"
        "title: Harvested sources\n"
        "description: One row per source saved with dev10x-kb:lesson-harvest — reach "
        "snapshot, beat structure, link to the day's notes.\n"
        "tags: [kb, lesson-harvest]\n"
        "status: stable\n"
        f"generated: {{ by: process:dev10x-kb, at: {now} }}\n"
        "---\n"
    )


def _splice(*, text: str, row: HubRow, generated: str) -> tuple[str, HubAction]:
    """Refresh or append ``row`` in the hub table — the one under HEADER only.

    Other tables in the note (the structure vocabulary, a user's own) are
    never touched, and a row matches only by the URL in its Title cell.
    """
    lines = text.splitlines()
    if lines and lines[0] == "---":
        for index in range(1, len(lines)):
            if lines[index] == "---":
                break
            if lines[index].startswith("generated:"):
                lines[index] = generated
    if HEADER not in lines:
        lines.extend(["", HEADER, DIVIDER, row.render()])
        return "\n".join(lines) + "\n", HubAction.APPENDED
    first_row = lines.index(HEADER) + 2
    end = first_row
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    action = HubAction.APPENDED
    for index in range(first_row, end):
        if _title_cell(lines[index]).endswith(row.key):
            lines[index] = row.render()
            action = HubAction.REFRESHED
    if action is HubAction.APPENDED:
        lines.insert(end, row.render())
    return "\n".join(lines) + "\n", action


def _lock_target(note: Path) -> Path:
    digest = hashlib.sha256(str(note.resolve()).encode("utf-8")).hexdigest()[:24]
    return Dev10xConfigDir.kb_locks_dir() / digest


def upsert_hub_row(
    *,
    config: KbConfig,
    source_id: str,
    name: str,
    structure: str,
    note: Path,
    directory: Path | None = None,
) -> Result[HubWrite]:
    """Add or refresh the source's row in the hub; a no-op when no hub is set."""
    if config.hub is None:
        return ok(HubWrite(path=None, action=HubAction.SKIPPED, reason="no `kb.hub` configured"))
    if any("\n" in value for value in (name, structure)):
        return err("name and structure must be single lines")
    checked_note = inside_vault(config=config, path=note)
    if not isinstance(checked_note, SuccessResult):
        return checked_note
    meta = read_meta(source_id=source_id, directory=directory)
    if not isinstance(meta, SuccessResult):
        return meta
    hub = config.hub
    row = build_row(
        meta=meta.value,
        name=name,
        structure=structure,
        note_link=relative_link(source=hub, target=note),
    )
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    generated = f"generated: {{ by: process:dev10x-kb, at: {now} }}"
    try:
        with file_lock(_lock_target(hub)):
            if hub.is_symlink():
                return err(f"{hub} is a symlink; refusing to write through it")
            if hub.is_file():
                spliced, action = _splice(
                    text=hub.read_text(encoding="utf-8"), row=row, generated=generated
                )
                atomic_write_text(hub, spliced)
                return ok(HubWrite(path=hub, action=action))
            hub.parent.mkdir(parents=True, exist_ok=True)
            body = f"{_frontmatter(now)}\n{INTRO}\n{HEADER}\n{DIVIDER}\n{row.render()}\n\n"
            atomic_write_text(hub, body + VOCABULARY)
            return ok(HubWrite(path=hub, action=HubAction.CREATED))
    except LockTimeoutError as exc:
        return err(str(exc), path=str(hub))
    except UnicodeDecodeError as exc:
        log.error("hub is not UTF-8", extra={"path": str(hub), "error": str(exc)})
        return err(f"{hub} is not valid UTF-8; fix or move it, then index again", path=str(hub))
    except OSError as exc:
        log.error("hub write failed", extra={"path": str(hub), "error": str(exc)})
        return err(f"cannot write {hub}: {exc}", path=str(hub))
