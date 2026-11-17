"""HTTP helpers and the external-tool checks (GH-1985)."""

from __future__ import annotations

import http.client as http_client
import io
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.kb import http, prerequisites


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _serve(monkeypatch: pytest.MonkeyPatch, body: bytes) -> list[Any]:
    requests: list[Any] = []

    def open_url(request: Any, timeout: float) -> _Response:
        requests.append(request)
        return _Response(body)

    monkeypatch.setattr(http._OPENER, "open", open_url)
    return requests


def _fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def open_url(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(http._OPENER, "open", open_url)


class TestFetchBytes:
    def test_returns_body_with_user_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        requests = _serve(monkeypatch, b"payload")

        result = http.fetch_bytes(url="https://example.com")

        assert isinstance(result, SuccessResult)
        assert (result.value, requests[0].get_header("User-agent")) == (
            b"payload",
            http.USER_AGENT,
        )

    def test_reports_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fail(monkeypatch)

        result = http.fetch_bytes(url="https://example.com")

        assert isinstance(result, ErrorResult)
        assert "Please try again" in result.error

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/feed", "//no-scheme"])
    def test_refuses_non_web_urls(self, url: str, monkeypatch: pytest.MonkeyPatch) -> None:
        requests = _serve(monkeypatch, b"secret")

        result = http.fetch_bytes(url=url)

        assert isinstance(result, ErrorResult)
        assert ("refusing non-http(s) URL" in result.error, requests) == (True, [])

    def test_stops_reading_past_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _serve(monkeypatch, b"0123456789")

        result = http.fetch_bytes(url="https://example.com", max_bytes=4)

        assert isinstance(result, ErrorResult)
        assert "larger than 4 bytes" in result.error


class _Truncated(_Response):
    def read(self, *_: object) -> bytes:
        raise http_client.IncompleteRead(b"par", 10)


class TestTruncatedResponses:
    def test_fetch_reports_an_incomplete_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(http._OPENER, "open", lambda request, timeout: _Truncated())

        result = http.fetch_bytes(url="https://example.com")

        assert isinstance(result, ErrorResult)
        assert "IncompleteRead" in result.error

    def test_download_removes_the_partial_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(http._OPENER, "open", lambda request, timeout: _Truncated())
        target = tmp_path / "file"

        result = http.download(url="https://cdn/a.mp3", destination=target)

        assert isinstance(result, ErrorResult)
        assert target.exists() is False


class TestRedirects:
    @pytest.mark.parametrize("target", ["file:///home/user/.ssh/id_rsa", "ftp://x/y"])
    def test_refuses_redirect_off_the_web(self, target: str) -> None:
        handler = http._HttpOnlyRedirects()
        request = urllib.request.Request("https://feed.example/rss")

        with pytest.raises(http.UnsafeUrlError, match="refusing redirect"):
            handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, target)

    def test_follows_web_redirect(self) -> None:
        handler = http._HttpOnlyRedirects()
        request = urllib.request.Request("https://feed.example/rss")

        redirected = handler.redirect_request(
            request, io.BytesIO(), 302, "Found", {}, "https://cdn.example/rss"
        )

        assert redirected is not None
        assert redirected.full_url == "https://cdn.example/rss"


class TestDownload:
    def test_streams_to_destination(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _serve(monkeypatch, b"audio")
        target = tmp_path / "sub" / "file"

        result = http.download(url="https://cdn/a.mp3", destination=target)

        assert isinstance(result, SuccessResult)
        assert target.read_bytes() == b"audio"

    def test_reports_network_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _fail(monkeypatch)

        result = http.download(url="https://cdn/a.mp3", destination=tmp_path / "file")

        assert isinstance(result, ErrorResult)
        assert "cannot download https://cdn/a.mp3" in result.error

    def test_stops_and_removes_oversized_download(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _serve(monkeypatch, b"x" * 10)
        monkeypatch.setattr(http, "_CHUNK_BYTES", 3)
        target = tmp_path / "file"

        result = http.download(url="https://cdn/a.mp3", destination=target, max_bytes=5)

        assert isinstance(result, ErrorResult)
        assert ("larger than 5 bytes" in result.error, target.exists()) == (True, False)

    def test_reports_oversize_when_cleanup_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _serve(monkeypatch, b"x" * 10)
        monkeypatch.setattr(http, "_CHUNK_BYTES", 3)

        def refuse_unlink(self: Path, missing_ok: bool = False) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(Path, "unlink", refuse_unlink)

        result = http.download(url="https://cdn/a.mp3", destination=tmp_path / "f", max_bytes=5)

        assert isinstance(result, ErrorResult)
        assert "larger than 5 bytes" in result.error


class TestPrerequisites:
    def test_require_returns_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: f"/opt/{name}")

        result = prerequisites.require(prerequisites.OBSIDIAN)

        assert isinstance(result, SuccessResult)
        assert result.value == "/opt/obsidian"

    def test_require_names_install_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)

        result = prerequisites.require(prerequisites.OBSIDIAN)

        assert isinstance(result, ErrorResult)
        assert "command line interface" in result.error

    def test_report_lists_every_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)

        report = prerequisites.report()

        assert sorted(report) == ["defuddle", "obsidian", "whisper-ctranslate2", "yt-dlp"]
        assert report["yt-dlp"]["install"] == "uv tool install yt-dlp"
