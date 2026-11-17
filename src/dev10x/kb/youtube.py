"""YouTube adapter: captions and reach metrics through yt-dlp (GH-1985).

`downsub.com` and a direct fetch of youtube.com both fail (JavaScript
rendering, consent redirect), so captions come from yt-dlp. Reach
numbers are a snapshot at fetch time and never update themselves.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import Result, SuccessResult, err, ok
from dev10x.kb.prerequisites import YT_DLP, require
from dev10x.kb.record import SourceKind, SourceRecord, SourceRef, is_safe_id

log = logging.getLogger(__name__)

YT_DLP_TIMEOUT_SECONDS = 180
_TAG = re.compile(r"<[^>]*>")
_ENTITIES = {"&nbsp;": " ", "&gt;": ">", "&lt;": "<", "&amp;": "&"}
_CAPTION_PREFERENCE = ("{id}.en-orig.vtt", "{id}.en.vtt", "{id}.*-orig.vtt", "{id}.*.vtt")


def clean_vtt(text: str) -> str:
    """WEBVTT minus headers, cue timings, inline tags and rolling-caption repeats."""
    lines: list[str] = []
    previous = ""
    for raw in text.splitlines():
        if raw.startswith(("WEBVTT", "Kind:", "Language:")) or "-->" in raw or not raw.strip():
            continue
        line = _TAG.sub("", raw)
        for entity, char in _ENTITIES.items():
            line = line.replace(entity, char)
        line = line.strip()
        if not line or line == previous:
            continue
        previous = line
        lines.append(line)
    return "\n".join(lines)


def _run(binary: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess_utils.run(
        [binary, *args],
        capture_output=True,
        text=True,
        timeout=YT_DLP_TIMEOUT_SECONDS,
    )


def _metadata(*, binary: str, url: str) -> Result[dict[str, object]]:
    try:
        completed = _run(binary, "--dump-single-json", "--skip-download", "--no-warnings", url)
    except subprocess.TimeoutExpired:
        return err(f"yt-dlp timed out reading {url}. Please try again.")
    if completed.returncode != 0:
        return err(f"yt-dlp could not read {url}: {completed.stderr.strip()[-400:]}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return err(f"yt-dlp returned unreadable metadata for {url}: {exc}")
    if not isinstance(data, dict):
        return err(f"yt-dlp returned unexpected metadata for {url}")
    return ok(data)


def _captions(*, binary: str, url: str, video_id: str) -> str:
    with tempfile.TemporaryDirectory(prefix="dev10x-kb-subs-") as scratch:
        try:
            completed = _run(
                binary,
                "--skip-download",
                "--write-auto-subs",
                "--write-subs",
                "--sub-langs",
                ".*-orig,en",
                "--sub-format",
                "vtt",
                "-o",
                f"{scratch}/%(id)s.%(ext)s",
                url,
            )
        except subprocess.TimeoutExpired:
            log.warning("caption download timed out", extra={"url": url})
            return ""
        if completed.returncode != 0:
            log.warning(
                "caption download failed",
                extra={"url": url, "stderr": completed.stderr.strip()[-400:]},
            )
        return _pick_caption(directory=Path(scratch), video_id=video_id)


def _pick_caption(*, directory: Path, video_id: str) -> str:
    for pattern in _CAPTION_PREFERENCE:
        for candidate in sorted(directory.glob(pattern.format(id=video_id))):
            if candidate.stat().st_size > 0:
                return clean_vtt(candidate.read_text(encoding="utf-8", errors="replace"))
    return ""


def _text(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    return "" if value is None else str(value)


def fetch_youtube(ref: SourceRef) -> Result[SourceRecord]:
    binary = require(YT_DLP)
    if not isinstance(binary, SuccessResult):
        return binary
    data = _metadata(binary=binary.value, url=ref.url)
    if not isinstance(data, SuccessResult):
        return data
    meta = data.value
    reported = _text(meta, "id")
    video_id = reported if is_safe_id(reported) else ref.id.removeprefix("yt-")
    return ok(
        SourceRecord(
            id=ref.id,
            kind=SourceKind.YOUTUBE,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=_text(meta, "title"),
            author=_text(meta, "uploader"),
            published=_text(meta, "upload_date"),
            duration=_text(meta, "duration_string"),
            description=_text(meta, "description"),
            transcript=_captions(binary=binary.value, url=ref.url, video_id=video_id),
            metrics={
                "views": _text(meta, "view_count"),
                "likes": _text(meta, "like_count"),
                "comments": _text(meta, "comment_count"),
                "channel_subs": _text(meta, "channel_follower_count"),
            },
        )
    )
