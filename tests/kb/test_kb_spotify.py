"""Spotify adapter: episode page, feed lookup and local transcription (GH-1985)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import ErrorResult, SuccessResult, err, ok
from dev10x.kb import http, spotify
from dev10x.kb.record import SourceKind, SourceRef

REF = SourceRef(
    kind=SourceKind.SPOTIFY,
    id="sp-7ywcdUyAXA3dNFKU4xjFeY",
    url="https://open.spotify.com/episode/7ywcdUyAXA3dNFKU4xjFeY",
)
PAGE = """<html><head>
<meta name="description" content="Listen to this episode. Show notes."/>
<meta name="music:duration" content="3725"/>
<meta name="music:release_date" content="2026-11-11T00:06:00Z"/>
<meta property="og:title" content="#504 – War: Drones &amp; Future"/>
<meta property="og:description" content="Example Podcast · Episode"/>
<meta property="og:title" content="ignored duplicate"/>
<link rel="x"/>
</head></html>"""
SEARCH = json.dumps(
    {
        "results": [
            {"collectionName": "Example Podcast | summaries", "feedUrl": "https://other/feed"},
            {"collectionName": "Example Podcast", "feedUrl": "https://impostor/feed"},
            {"collectionName": "No feed"},
            "not a dict",
            {"collectionName": "Example Podcast", "feedUrl": "https://real/feed"},
        ]
    }
).encode()
ITUNES = 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"'
REAL_FEED = f"""<rss {ITUNES}><channel><itunes:author>Host</itunes:author>
<item><title>#503 – Older</title><enclosure url="https://cdn/503.mp3"/></item>
<item><title>#504 - War: Drones &amp; Future</title>
<enclosure url="https://cdn/504.mp3"/><itunes:author>Guest Host</itunes:author></item>
</channel></rss>""".encode()
IMPOSTOR_FEED = b"<rss><channel><item><title>Something else</title></item></channel></rss>"


def _completed(*, returncode: int = 0, stderr: str = "") -> Any:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    pages: dict[str, Any] = {
        REF.url: ok(PAGE.encode()),
        "https://impostor/feed": ok(IMPOSTOR_FEED),
        "https://real/feed": ok(REAL_FEED),
        "https://other/feed": err("unreachable"),
    }

    def fetch(*, url: str, **_: Any) -> Any:
        return pages.get(url, ok(SEARCH))

    def download(*, url: str, destination: Path, **_: Any) -> Any:
        destination.write_bytes(url.encode())
        return ok(destination)

    monkeypatch.setattr(http, "fetch_bytes", fetch)
    monkeypatch.setattr(http, "download", download)
    return pages


@pytest.fixture
def whisper(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(args: list[str], **_: Any) -> Any:
        calls.append(args)
        out = Path(args[args.index("--output_dir") + 1])
        (out / "episode.txt").write_text("spoken words\n")
        return _completed()

    monkeypatch.setattr(subprocess_utils, "run", run)
    return calls


class TestParseEpisodePage:
    def test_reads_episode_and_show(self) -> None:
        result = spotify.parse_episode_page(PAGE)

        assert isinstance(result, SuccessResult)
        assert result.value == spotify.EpisodePage(
            title="#504 – War: Drones & Future",
            show="Example Podcast",
            description="Listen to this episode. Show notes.",
            duration_seconds="3725",
            published="2026-11-11T00:06:00Z",
        )

    def test_rejects_non_episode_page(self) -> None:
        page = (
            '<meta property="og:title" content="Show"/>'
            '<meta property="og:description" content="Podcast · Host"/>'
        )

        assert isinstance(spotify.parse_episode_page(page), ErrorResult)


class TestCandidateFeeds:
    def test_exact_show_matches_come_first(self) -> None:
        assert spotify.candidate_feeds(payload=SEARCH, show="Example Podcast") == [
            "https://impostor/feed",
            "https://real/feed",
            "https://other/feed",
        ]

    @pytest.mark.parametrize("payload", [b"not json", b"[1]"])
    def test_unreadable_search_yields_nothing(self, payload: bytes) -> None:
        assert spotify.candidate_feeds(payload=payload, show="X") == []


class TestFindEpisode:
    def test_accepts_a_declared_utf8_feed(self) -> None:
        feed = b'<?xml version="1.0" encoding="UTF-8"?>' + REAL_FEED

        result = spotify.find_episode(feed=feed, feed_url="f", title="#503 Older")

        assert isinstance(result, SuccessResult)
        assert result.value is not None

    def test_matches_title_across_dash_styles(self) -> None:
        result = spotify.find_episode(
            feed=REAL_FEED, feed_url="https://real/feed", title="#504 – War: Drones & Future"
        )

        assert isinstance(result, SuccessResult)
        assert result.value == spotify.FeedEpisode(
            feed_url="https://real/feed", audio_url="https://cdn/504.mp3", author="Guest Host"
        )

    def test_falls_back_to_channel_author(self) -> None:
        result = spotify.find_episode(feed=REAL_FEED, feed_url="f", title="#503 Older")

        assert isinstance(result, SuccessResult)
        assert result.value is not None
        assert result.value.author == "Host"

    def test_absent_episode_is_none(self) -> None:
        result = spotify.find_episode(feed=IMPOSTOR_FEED, feed_url="f", title="#504")

        assert isinstance(result, SuccessResult)
        assert result.value is None

    @pytest.mark.parametrize(
        ("feed", "message"),
        [
            (b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>', "DTD or entities"),
            (b"<!--" + b"x" * 5000 + b"--><!doctype rss><rss/>", "DTD or entities"),
            ("<rss/>".encode("utf-16"), "UTF-16/32 encoded"),
            (b"<r\x00s\x00s\x00/>", "UTF-16/32 encoded"),
            (b"<rss>\xe9t\xe9</rss>", "not UTF-8"),
            (b'<?xml version="1.0" encoding="cp037"?><rss/>', "declares encoding 'cp037'"),
            (b"<rss><channel><item><title>T</title></item>", "not valid XML"),
            (b"<rss><channel><item><title>T</title></item></channel></rss>", "no audio"),
        ],
    )
    def test_reports_unusable_feeds(self, feed: bytes, message: str) -> None:
        result = spotify.find_episode(feed=feed, feed_url="f", title="T")

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_refuses_oversized_feed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(spotify, "MAX_FEED_BYTES", 10)

        result = spotify.find_episode(feed=REAL_FEED, feed_url="f", title="T")

        assert isinstance(result, ErrorResult)
        assert "larger than" in result.error


class TestTranscribe:
    def test_passes_model_and_reads_text(self, whisper: list[list[str]], tmp_path: Path) -> None:
        result = spotify.transcribe(binary="w", audio=tmp_path / "a", model="medium")

        assert isinstance(result, SuccessResult)
        assert (result.value, whisper[0][2:6]) == (
            "spoken words",
            ["--model", "medium", "--output_format", "txt"],
        )

    @pytest.mark.parametrize(
        ("completed", "message"),
        [
            (_completed(returncode=1, stderr="CUDA error"), "CUDA error"),
            (_completed(), "no transcript"),
        ],
    )
    def test_reports_failures(
        self, completed: Any, message: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(subprocess_utils, "run", lambda args, **_: completed)

        result = spotify.transcribe(binary="w", audio=tmp_path / "a", model="small")

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_reports_timeout(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def run(args: list[str], **_: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd=args, timeout=1)

        monkeypatch.setattr(subprocess_utils, "run", run)

        result = spotify.transcribe(binary="w", audio=tmp_path / "a", model="small")

        assert isinstance(result, ErrorResult)
        assert "Please try again" in result.error


class TestFetchSpotify:
    def test_transcribes_audio_from_the_verified_feed(
        self, web: dict[str, Any], whisper: list[list[str]]
    ) -> None:
        result = spotify.fetch_spotify(REF, model="base")

        assert isinstance(result, SuccessResult)
        record = result.value
        assert (record.title, record.author, record.duration, record.transcript) == (
            "#504 – War: Drones & Future",
            "Guest Host",
            "1:02:05",
            "spoken words",
        )
        assert record.metrics == {"show": "Example Podcast", "feed": "https://real/feed"}

    def test_spotify_exclusive_episode_is_unreachable(
        self, web: dict[str, Any], whisper: list[list[str]]
    ) -> None:
        web["https://real/feed"] = ok(IMPOSTOR_FEED)

        result = spotify.fetch_spotify(REF)

        assert isinstance(result, ErrorResult)
        assert result.error.endswith(
            "Spotify-exclusive shows cannot be harvested. Feeds rejected: unreachable"
        )

    def test_names_every_rejected_feed(
        self, web: dict[str, Any], whisper: list[list[str]]
    ) -> None:
        web["https://real/feed"] = ok(b"<!DOCTYPE x><rss/>")
        web["https://other/feed"] = ok(IMPOSTOR_FEED)

        result = spotify.fetch_spotify(REF)

        assert isinstance(result, ErrorResult)
        assert result.error.endswith(
            "Feeds rejected: feed https://real/feed declares a DTD or entities; "
            "refusing to parse it"
        )

    def test_search_term_encodes_slashes(
        self, web: dict[str, Any], whisper: list[list[str]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []
        original = http.fetch_bytes

        def recording(*, url: str, **kwargs: Any) -> Any:
            seen.append(url)
            return original(url=url, **kwargs)

        monkeypatch.setattr(http, "fetch_bytes", recording)
        web[REF.url] = ok(PAGE.replace("Example Podcast ·", "AC/DC Talk ·").encode())

        spotify.fetch_spotify(REF)

        assert seen[1].endswith("term=AC%2FDC%20Talk")

    @pytest.mark.parametrize(
        "broken",
        [REF.url, "search"],
    )
    def test_reports_unreachable_pages(
        self,
        broken: str,
        web: dict[str, Any],
        whisper: list[list[str]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fetch(*, url: str, **_: Any) -> Any:
            hit = url == broken or (broken == "search" and "itunes" in url)
            return err("down") if hit else web.get(url, ok(SEARCH))

        monkeypatch.setattr(http, "fetch_bytes", fetch)

        assert isinstance(spotify.fetch_spotify(REF), ErrorResult)

    def test_reports_non_episode_page(self, web: dict[str, Any], whisper: list[list[str]]) -> None:
        web[REF.url] = ok(b"<html></html>")

        assert isinstance(spotify.fetch_spotify(REF), ErrorResult)

    def test_reports_failed_download(
        self, web: dict[str, Any], whisper: list[list[str]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(http, "download", lambda **_: err("cannot download"))

        result = spotify.fetch_spotify(REF)

        assert isinstance(result, ErrorResult)
        assert "cannot download" in result.error

    def test_reports_failed_transcription(
        self, web: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess_utils, "run", lambda args, **_: _completed(returncode=1))

        assert isinstance(spotify.fetch_spotify(REF), ErrorResult)

    def test_missing_whisper_names_install_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)

        result = spotify.fetch_spotify(REF)

        assert isinstance(result, ErrorResult)
        assert "uv tool install whisper-ctranslate2" in result.error


@pytest.mark.parametrize(
    ("seconds", "clock"),
    [("59", "0:59"), ("3725", "1:02:05"), ("", ""), ("n/a", "")],
)
def test_clock_formats_duration(seconds: str, clock: str) -> None:
    assert spotify._clock(seconds) == clock
