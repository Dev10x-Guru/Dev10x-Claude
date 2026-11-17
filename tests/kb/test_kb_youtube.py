"""YouTube adapter: yt-dlp metadata, caption choice and VTT cleaning (GH-1985)."""

from __future__ import annotations

import json
import subprocess
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

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _completed(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")


def _runner(*, metadata: Any, captions: dict[str, str], caption_exit: Any = None) -> Runner:
    def run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        if "--dump-single-json" in args:
            return metadata
        target = Path(args[args.index("-o") + 1]).parent
        for name, text in captions.items():
            (target / name).write_text(text)
        return caption_exit or _completed()

    return run


def test_clean_vtt_drops_headers_timings_tags_and_repeats() -> None:
    assert youtube.clean_vtt(VTT) == "hello there\na > b & c"


def test_unsafe_metadata_id_falls_back_to_the_link_id(monkeypatch: pytest.MonkeyPatch) -> None:
    hostile = {**META, "id": "../../etc/x*"}
    monkeypatch.setattr(
        subprocess_utils,
        "run",
        _runner(metadata=_completed(stdout=json.dumps(hostile)), captions={"vid1.en.vtt": VTT}),
    )

    result = youtube.fetch_youtube(REF)

    assert isinstance(result, SuccessResult)
    assert (result.value.url, result.value.transcript) == (
        "https://www.youtube.com/watch?v=vid1",
        "hello there\na > b & c",
    )


def test_failed_caption_download_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        subprocess_utils,
        "run",
        _runner(
            metadata=_completed(stdout=json.dumps(META)),
            captions={},
            caption_exit=_completed(returncode=1, stderr="HTTP Error 429"),
        ),
    )

    result = youtube.fetch_youtube(REF)

    assert isinstance(result, SuccessResult)
    assert (result.value.transcript, caplog.records[-1].getMessage()) == (
        "",
        "caption download failed",
    )


class TestFetchYoutube:
    def test_builds_record_with_metrics_and_captions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess_utils,
            "run",
            _runner(metadata=_completed(stdout=json.dumps(META)), captions={"vid1.en.vtt": VTT}),
        )

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

    def test_prefers_english_over_other_original_captions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captions = {"vid1.en.vtt": "WEBVTT\n\nenglish", "vid1.pl-orig.vtt": "WEBVTT\n\npolski"}
        monkeypatch.setattr(
            subprocess_utils,
            "run",
            _runner(metadata=_completed(stdout=json.dumps(META)), captions=captions),
        )

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, SuccessResult)
        assert result.value.transcript == "english"

    def test_skips_empty_caption_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captions = {"vid1.en-orig.vtt": "", "vid1.de.vtt": "WEBVTT\n\ndeutsch"}
        monkeypatch.setattr(
            subprocess_utils,
            "run",
            _runner(metadata=_completed(stdout=json.dumps(META)), captions=captions),
        )

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, SuccessResult)
        assert result.value.transcript == "deutsch"

    def test_no_captions_leaves_transcript_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess_utils,
            "run",
            _runner(metadata=_completed(stdout=json.dumps(META)), captions={}),
        )

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, SuccessResult)
        assert result.value.transcript == ""

    def test_caption_timeout_leaves_transcript_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            if "--dump-single-json" in args:
                return _completed(stdout=json.dumps(META))
            raise subprocess.TimeoutExpired(cmd=args, timeout=1)

        monkeypatch.setattr(subprocess_utils, "run", run)

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, SuccessResult)
        assert result.value.transcript == ""

    @pytest.mark.parametrize(
        ("metadata", "message"),
        [
            (_completed(returncode=1, stderr="ERROR: private video"), "private video"),
            (_completed(stdout="not json"), "unreadable metadata"),
            (_completed(stdout="[]"), "unexpected metadata"),
        ],
    )
    def test_reports_metadata_failures(
        self, metadata: Any, message: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess_utils, "run", _runner(metadata=metadata, captions={}))

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_reports_metadata_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=args, timeout=1)

        monkeypatch.setattr(subprocess_utils, "run", run)

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, ErrorResult)
        assert "Please try again" in result.error

    def test_missing_yt_dlp_names_install_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)

        result = youtube.fetch_youtube(REF)

        assert isinstance(result, ErrorResult)
        assert "uv tool install yt-dlp" in result.error
