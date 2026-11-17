"""YouTube adapter: yt-dlp metadata, caption choice and VTT cleaning (GH-1985)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.kb import youtube
from dev10x.kb.record import SourceKind, SourceRef

REF = SourceRef(kind=SourceKind.YOUTUBE, id="yt-vid1", url="https://youtu.be/vid1")
META = {
    "id": "vid1",
    "title": "Talk",
    "uploader": "Speaker",
    "upload_date": "20261101",
    "duration_string": "12:00",
    "description": "About things",
    "view_count": 1000,
    "like_count": 50,
    "comment_count": None,
    "channel_follower_count": 2000,
}
VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:01.000
<c>hello</c>&nbsp;there

00:00:01.000 --> 00:00:02.000
hello there

00:00:02.000 --> 00:00:03.000
a &gt; b &amp; c
"""

pytestmark = pytest.mark.usefixtures("tools_installed")

Install = Callable[..., None]


@pytest.fixture
def yt_dlp(monkeypatch: pytest.MonkeyPatch, completed: Any) -> Install:
    """Fake yt-dlp: the metadata call and the caption call, dispatched by flag."""

    def install(
        *,
        metadata: Any,
        captions: dict[str, str],
        caption_outcome: Any = None,
        overrides: dict[str, Callable[[list[str]], Any]] | None = None,
    ) -> None:
        caption_result = caption_outcome or completed()

        def write_captions(args: list[str]) -> Any:
            target = Path(args[args.index("-o") + 1]).parent
            for name, text in captions.items():
                (target / name).write_text(text)
            return caption_result

        handlers = {
            "--dump-single-json": lambda args: metadata,
            "--skip-download": write_captions,
            **(overrides or {}),
        }
        monkeypatch.setattr(subprocess_utils, "run", lambda args, **_: handlers[args[1]](args))

    return install


@pytest.fixture
def meta_ok(completed: Any) -> Any:
    return completed(stdout=json.dumps(META))


def test_clean_vtt_drops_headers_timings_tags_and_repeats() -> None:
    assert youtube.clean_vtt(VTT) == "hello there\na > b & c"


def test_unsafe_metadata_id_falls_back_to_the_link_id(yt_dlp: Install, completed: Any) -> None:
    hostile = {**META, "id": "../../etc/x*"}
    yt_dlp(metadata=completed(stdout=json.dumps(hostile)), captions={"vid1.en.vtt": VTT})

    result = youtube.fetch_youtube(REF)

    assert isinstance(result, SuccessResult)
    assert (result.value.url, result.value.transcript) == (
        "https://www.youtube.com/watch?v=vid1",
        "hello there\na > b & c",
    )


def test_failed_caption_download_is_logged(
    yt_dlp: Install, meta_ok: Any, completed: Any, caplog: pytest.LogCaptureFixture
) -> None:
    yt_dlp(
        metadata=meta_ok,
        captions={},
        caption_outcome=completed(returncode=1, stderr="HTTP Error 429"),
    )

    result = youtube.fetch_youtube(REF)

    assert isinstance(result, SuccessResult)
    assert result.value.transcript == ""
    assert caplog.records[-1].getMessage() == "caption download failed"


class TestFetchYoutube:
    def test_builds_record_with_metrics_and_captions(self, yt_dlp: Install, meta_ok: Any) -> None:
        yt_dlp(metadata=meta_ok, captions={"vid1.en.vtt": VTT})

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, SuccessResult)
        record = result.value
        assert (record.url, record.title, record.author, record.transcript) == (
            "https://www.youtube.com/watch?v=vid1",
            "Talk",
            "Speaker",
            "hello there\na > b & c",
        )
        assert record.metrics == {
            "views": "1000",
            "likes": "50",
            "comments": "",
            "channel_subs": "2000",
        }

    @pytest.mark.parametrize(
        ("captions", "transcript"),
        [
            ({"vid1.en.vtt": "WEBVTT\n\nenglish", "vid1.pl-orig.vtt": "WEBVTT\n\npl"}, "english"),
            ({"vid1.en-orig.vtt": "WEBVTT\n\norig", "vid1.en.vtt": "WEBVTT\n\nen"}, "orig"),
            ({"vid1.en-orig.vtt": "", "vid1.de.vtt": "WEBVTT\n\ndeutsch"}, "deutsch"),
            ({}, ""),
        ],
        ids=["english-over-other-original", "original-english-first", "skips-empty", "none"],
    )
    def test_picks_captions_by_preference(
        self, captions: dict[str, str], transcript: str, yt_dlp: Install, meta_ok: Any
    ) -> None:
        yt_dlp(metadata=meta_ok, captions=captions)

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, SuccessResult)
        assert result.value.transcript == transcript

    def test_caption_timeout_leaves_transcript_empty(
        self, yt_dlp: Install, meta_ok: Any, timeout_run: Callable[..., Any]
    ) -> None:
        yt_dlp(
            metadata=meta_ok,
            captions={},
            overrides={"--skip-download": lambda args: timeout_run(args)},
        )

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, SuccessResult)
        assert result.value.transcript == ""

    @pytest.mark.parametrize(
        ("outcome", "message"),
        [
            ({"returncode": 1, "stderr": "ERROR: private video"}, "private video"),
            ({"stdout": "not json"}, "unreadable metadata"),
            ({"stdout": "[]"}, "unexpected metadata"),
        ],
    )
    def test_reports_metadata_failures(
        self, outcome: dict[str, Any], message: str, yt_dlp: Install, completed: Any
    ) -> None:
        yt_dlp(metadata=completed(**outcome), captions={})

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_reports_metadata_timeout(
        self, monkeypatch: pytest.MonkeyPatch, timeout_run: Callable[..., Any]
    ) -> None:
        monkeypatch.setattr(subprocess_utils, "run", timeout_run)

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, ErrorResult)
        assert result.error == f"yt-dlp timed out reading {REF.url}. Please try again."

    def test_missing_yt_dlp_names_install_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, ErrorResult)
        assert "uv tool install yt-dlp" in result.error
