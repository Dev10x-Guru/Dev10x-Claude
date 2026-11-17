"""Spotify episode adapter: public RSS audio, transcribed locally (GH-1985).

Spotify publishes no transcript API and its streams are DRM-protected,
so the audio comes from the show's own public RSS feed instead:

1. the episode page's Open Graph tags give the episode and show titles;
2. the iTunes Search API maps the show title to candidate feed URLs;
3. a feed counts only when it carries an item with the same episode
   title — several unrelated feeds can share a show's name;
4. the item's enclosure is downloaded and transcribed with
   whisper-ctranslate2 (faster-whisper).

A Spotify-exclusive show has no public feed and is reported as
unreachable rather than summarized from its description.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import Result, SuccessResult, err, ok
from dev10x.kb import http
from dev10x.kb.prerequisites import WHISPER, require
from dev10x.kb.record import SourceKind, SourceRecord, SourceRef

log = logging.getLogger(__name__)

ITUNES_SEARCH = "https://itunes.apple.com/search?media=podcast&entity=podcast&limit=10&term={term}"
MAX_FEED_BYTES = 30 * 1024 * 1024
TRANSCRIBE_TIMEOUT_SECONDS = 4 * 60 * 60
DEFAULT_MODEL = "small"
_ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
_WIDE_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")
# The DTD guard searches decoded UTF-8 text, so a declaration naming
# another encoding (cp037 hides "<!DOCTYPE" from a byte search) is refused.
_XML_ENCODING = re.compile(r"<\?xml[^>]*encoding\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_UTF8_NAMES = frozenset({"utf-8", "utf8", "us-ascii", "ascii"})
_DTD = re.compile(r"<!(?:doctype|entity)", re.IGNORECASE)
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


@dataclass(frozen=True)
class EpisodePage:
    title: str
    show: str
    description: str
    duration_seconds: str
    published: str


@dataclass(frozen=True)
class FeedEpisode:
    feed_url: str
    audio_url: str
    author: str


class _MetaTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = dict(attrs)
        key = attributes.get("property") or attributes.get("name")
        content = attributes.get("content")
        if key and content is not None and key not in self.tags:
            self.tags[key] = content


def normalize_title(title: str) -> str:
    """Compare titles by words, ignoring punctuation, dashes and case."""
    return _NON_WORD.sub(" ", title).casefold().strip()


def parse_episode_page(html: str) -> Result[EpisodePage]:
    parser = _MetaTags()
    parser.feed(html)
    tags = parser.tags
    title = tags.get("og:title", "").strip()
    show, _, kind = tags.get("og:description", "").partition(" · ")
    if not title or not show.strip() or "Episode" not in kind:
        return err("the Spotify page carries no episode title and show name")
    return ok(
        EpisodePage(
            title=title,
            show=show.strip(),
            description=tags.get("description", "").strip(),
            duration_seconds=tags.get("music:duration", ""),
            published=tags.get("music:release_date", ""),
        )
    )


def candidate_feeds(*, payload: bytes, show: str) -> list[str]:
    """Feed URLs from an iTunes search, exact show-name matches first."""
    try:
        results = json.loads(payload).get("results", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    wanted = normalize_title(show)
    exact: list[str] = []
    other: list[str] = []
    for result in results:
        feed = result.get("feedUrl") if isinstance(result, dict) else None
        if not feed:
            continue
        name = normalize_title(str(result.get("collectionName", "")))
        (exact if name == wanted else other).append(str(feed))
    return exact + other


def find_episode(*, feed: bytes, feed_url: str, title: str) -> Result[FeedEpisode | None]:
    """The feed item whose title matches ``title``; ``None`` when absent."""
    if len(feed) > MAX_FEED_BYTES:
        return err(f"feed {feed_url} is larger than {MAX_FEED_BYTES} bytes")
    if b"\x00" in feed or feed.startswith(_WIDE_BOMS):
        return err(f"feed {feed_url} is UTF-16/32 encoded; refusing to parse it")
    try:
        text = feed.decode("utf-8")
    except UnicodeDecodeError:
        return err(f"feed {feed_url} is not UTF-8; refusing to parse it")
    declared = _XML_ENCODING.search(text[:512])
    if declared and declared.group(1).lower() not in _UTF8_NAMES:
        return err(
            f"feed {feed_url} declares encoding {declared.group(1)!r}; only UTF-8 is parsed"
        )
    if _DTD.search(text):
        return err(f"feed {feed_url} declares a DTD or entities; refusing to parse it")
    try:
        root = ElementTree.fromstring(feed)
    except ElementTree.ParseError as exc:
        return err(f"feed {feed_url} is not valid XML: {exc}")
    wanted = normalize_title(title)
    channel_author = root.findtext(f"channel/{_ITUNES_NS}author") or ""
    for item in root.iter("item"):
        if normalize_title(item.findtext("title") or "") != wanted:
            continue
        enclosure = item.find("enclosure")
        audio = enclosure.get("url") if enclosure is not None else None
        if not audio:
            return err(f"episode {title!r} in {feed_url} has no audio enclosure")
        author = item.findtext(f"{_ITUNES_NS}author") or channel_author
        return ok(FeedEpisode(feed_url=feed_url, audio_url=audio, author=author.strip()))
    return ok(None)


def _locate_audio(page: EpisodePage) -> Result[FeedEpisode]:
    search = http.fetch_bytes(url=ITUNES_SEARCH.format(term=quote(page.show, safe="")))
    if not isinstance(search, SuccessResult):
        return search
    rejected: list[str] = []
    for feed_url in candidate_feeds(payload=search.value, show=page.show):
        feed = http.fetch_bytes(url=feed_url, max_bytes=MAX_FEED_BYTES)
        if not isinstance(feed, SuccessResult):
            rejected.append(feed.error)
            continue
        found = find_episode(feed=feed.value, feed_url=feed_url, title=page.title)
        if not isinstance(found, SuccessResult):
            log.warning("feed rejected", extra={"feed": feed_url, "error": found.error})
            rejected.append(found.error)
            continue
        if found.value is not None:
            return ok(found.value)
    reasons = f" Feeds rejected: {'; '.join(rejected)}" if rejected else ""
    return err(
        f"no public feed of {page.show!r} carries the episode {page.title!r}; "
        f"Spotify-exclusive shows cannot be harvested.{reasons}"
    )


def transcribe(*, binary: str, audio: Path, model: str) -> Result[str]:
    with tempfile.TemporaryDirectory(prefix="dev10x-kb-whisper-") as scratch:
        try:
            completed = subprocess_utils.run(
                [
                    binary,
                    str(audio),
                    "--model",
                    model,
                    "--output_format",
                    "txt",
                    "--output_dir",
                    scratch,
                    "--verbose",
                    "False",
                ],
                capture_output=True,
                text=True,
                timeout=TRANSCRIBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return err(f"transcribing {audio.name} timed out. Please try again.")
        if completed.returncode != 0:
            return err(f"whisper-ctranslate2 failed: {completed.stderr.strip()[-400:]}")
        outputs = sorted(Path(scratch).glob("*.txt"))
        if not outputs:
            return err("whisper-ctranslate2 produced no transcript")
        return ok(outputs[0].read_text(encoding="utf-8").strip())


def fetch_spotify(ref: SourceRef, *, model: str = DEFAULT_MODEL) -> Result[SourceRecord]:
    binary = require(WHISPER)
    if not isinstance(binary, SuccessResult):
        return binary
    html = http.fetch_bytes(url=ref.url)
    if not isinstance(html, SuccessResult):
        return html
    page = parse_episode_page(html.value.decode("utf-8", errors="replace"))
    if not isinstance(page, SuccessResult):
        return page
    episode = _locate_audio(page.value)
    if not isinstance(episode, SuccessResult):
        return episode
    with tempfile.TemporaryDirectory(prefix="dev10x-kb-audio-") as scratch:
        audio = http.download(url=episode.value.audio_url, destination=Path(scratch) / "episode")
        if not isinstance(audio, SuccessResult):
            return audio
        text = transcribe(binary=binary.value, audio=audio.value, model=model)
    if not isinstance(text, SuccessResult):
        return text
    return ok(
        SourceRecord(
            id=ref.id,
            kind=SourceKind.SPOTIFY,
            url=ref.url,
            title=page.value.title,
            author=episode.value.author or page.value.show,
            published=page.value.published,
            duration=_clock(page.value.duration_seconds),
            description=page.value.description,
            transcript=text.value,
            metrics={"show": page.value.show, "feed": episode.value.feed_url},
        )
    )


def _clock(seconds: str) -> str:
    if not seconds.isdigit():
        return ""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
