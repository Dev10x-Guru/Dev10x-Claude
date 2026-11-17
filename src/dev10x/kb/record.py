"""One normalized record per lesson source (GH-1985).

A video, an article and a podcast episode carry different metadata, but
everything downstream — insight agents, persistence, the hub row — reads
the same two files: ``<id>.txt`` (the text to learn from) and
``<id>.meta.txt`` (``key: value`` lines, a ``---`` separator, then the
free-text description). Adapters only have to produce a ``SourceRecord``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dev10x.core.diagnostic_log import ensure_private_dir
from dev10x.core.domain.common.result import Result, err, ok

log = logging.getLogger(__name__)

NO_TRANSCRIPT = "(no transcript available)"
META_SEPARATOR = "---"

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_SPOTIFY_EPISODE = re.compile(r"^/(?:intl-[a-z]{2}/)?episode/([A-Za-z0-9]{22})/?$")
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")


class SourceKind(StrEnum):
    YOUTUBE = "youtube"
    WEB = "web"
    SPOTIFY = "spotify"


@dataclass(frozen=True)
class SourceRef:
    """What a URL points at, before anything is fetched."""

    kind: SourceKind
    id: str
    url: str


@dataclass(frozen=True)
class SourceRecord:
    id: str
    kind: SourceKind
    url: str
    title: str
    author: str = ""
    published: str = ""
    duration: str = ""
    description: str = ""
    transcript: str = ""
    metrics: dict[str, str] = field(default_factory=dict)
    measured_at: str = field(default_factory=lambda: date.today().isoformat())

    def meta_text(self) -> str:
        fields = {
            "kind": self.kind.value,
            "title": self.title,
            "author": self.author,
            "url": self.url,
            "published": self.published,
            "duration": self.duration,
            **self.metrics,
            "measured_at": self.measured_at,
        }
        header = [f"{key}: {_one_line(value)}" for key, value in fields.items()]
        return "\n".join([*header, META_SEPARATOR, self.description.strip()]) + "\n"


@dataclass(frozen=True)
class RecordFiles:
    id: str
    kind: SourceKind
    text: Path
    meta: Path
    text_lines: int
    has_transcript: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "text": str(self.text),
            "meta": str(self.meta),
            "text_lines": self.text_lines,
            "has_transcript": self.has_transcript,
        }


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def is_safe_id(value: str) -> bool:
    """True for an id that is safe in a file name, a glob and a URL.

    ``fullmatch``, not ``match`` with ``$``: ``$`` also matches before a
    trailing newline, which would let ``"abc\\n"`` through.
    """
    return bool(_SAFE_ID.fullmatch(value))


def classify_url(url: str) -> Result[SourceRef]:
    """Map a pasted link to the adapter that can read it."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return err(f"{url!r} is not an http(s) URL; supported: YouTube, Spotify episodes, web")
    host = parsed.netloc.lower().split(":")[0]
    if host in _YOUTUBE_HOSTS or host == "youtu.be":
        video = _youtube_id(host=host, path=parsed.path, query=parsed.query)
        if video is None:
            return err(f"{url!r} is a YouTube link but not a video (watch, shorts or youtu.be)")
        return ok(SourceRef(kind=SourceKind.YOUTUBE, id=f"yt-{video}", url=url.strip()))
    if host == "open.spotify.com":
        match = _SPOTIFY_EPISODE.match(parsed.path)
        if match is None:
            return err(f"{url!r} is a Spotify link but not an episode; only episodes have audio")
        episode = match.group(1)
        canonical = f"https://open.spotify.com/episode/{episode}"
        return ok(SourceRef(kind=SourceKind.SPOTIFY, id=f"sp-{episode}", url=canonical))
    digest = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:12]
    return ok(SourceRef(kind=SourceKind.WEB, id=f"web-{digest}", url=url.strip()))


def _youtube_id(*, host: str, path: str, query: str) -> str | None:
    if host == "youtu.be":
        candidate = path.strip("/").split("/")[0]
    elif path.startswith("/shorts/") or path.startswith("/live/"):
        candidate = path.split("/")[2] if len(path.split("/")) > 2 else ""
    elif path.rstrip("/") == "/watch":
        candidate = parse_qs(query).get("v", [""])[0]
    else:
        return None
    return candidate if is_safe_id(candidate) else None


def workdir() -> Path:
    """Ephemeral home of fetched records; a reboot may clear it."""
    return Path(tempfile.gettempdir()) / "Dev10x" / "kb"


def first_symlink(*paths: Path) -> Path | None:
    return next((path for path in paths if path.is_symlink()), None)


def write_record(*, record: SourceRecord, directory: Path | None = None) -> Result[RecordFiles]:
    target = directory or workdir()
    if not is_safe_id(record.id):
        return err(f"unsafe source id {record.id!r}")
    text_path = target / f"{record.id}.txt"
    meta_path = target / f"{record.id}.meta.txt"
    linked = first_symlink(target, text_path, meta_path)
    if linked:
        return err(f"{linked} is a symlink; refusing to write a record through it")
    try:
        ensure_private_dir(directory=target)
        body = record.transcript.strip()
        text_path.write_text((body or NO_TRANSCRIPT) + "\n", encoding="utf-8")
        meta_path.write_text(record.meta_text(), encoding="utf-8")
    except OSError as exc:
        log.error("record write failed", extra={"id": record.id, "error": str(exc)})
        return err(f"cannot write record {record.id}: {exc}")
    return ok(
        RecordFiles(
            id=record.id,
            kind=record.kind,
            text=text_path,
            meta=meta_path,
            text_lines=len((body or NO_TRANSCRIPT).splitlines()),
            has_transcript=bool(body),
        )
    )


def read_meta(*, source_id: str, directory: Path | None = None) -> Result[dict[str, str]]:
    """The ``key: value`` header of a fetched record, without its description."""
    if not is_safe_id(source_id):
        return err(f"unsafe source id {source_id!r}")
    path = (directory or workdir()) / f"{source_id}.meta.txt"
    if first_symlink(path):
        return err(f"{path} is a symlink; refusing to read a record through it")
    if not path.is_file() or path.stat().st_size == 0:
        return err(f"missing or empty {path}; run `dev10x skill kb fetch` first")
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == META_SEPARATOR:
            break
        key, sep, value = line.partition(": ")
        if sep:
            fields[key] = value
    return ok(fields)
