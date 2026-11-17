"""Source classification and the normalized record files (GH-1985)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.kb.record import (
    NO_TRANSCRIPT,
    RecordFiles,
    SourceKind,
    SourceRecord,
    classify_url,
    is_safe_id,
    read_meta,
    workdir,
    write_record,
)


class TestClassifyUrl:
    @pytest.mark.parametrize(
        ("url", "kind", "source_id"),
        [
            ("https://www.youtube.com/watch?v=abc123DEF_-", SourceKind.YOUTUBE, "yt-abc123DEF_-"),
            ("https://youtube.com/shorts/xyz789", SourceKind.YOUTUBE, "yt-xyz789"),
            ("https://m.youtube.com/live/LIVE01", SourceKind.YOUTUBE, "yt-LIVE01"),
            ("https://youtu.be/short01?t=3", SourceKind.YOUTUBE, "yt-short01"),
            (
                "https://open.spotify.com/episode/7ywcdUyAXA3dNFKU4xjFeY?si=1",
                SourceKind.SPOTIFY,
                "sp-7ywcdUyAXA3dNFKU4xjFeY",
            ),
            (
                "https://open.spotify.com/intl-pl/episode/7ywcdUyAXA3dNFKU4xjFeY",
                SourceKind.SPOTIFY,
                "sp-7ywcdUyAXA3dNFKU4xjFeY",
            ),
        ],
    )
    def test_maps_url_to_kind_and_id(self, url: str, kind: SourceKind, source_id: str) -> None:
        result = classify_url(url)

        assert isinstance(result, SuccessResult)
        assert (result.value.kind, result.value.id) == (kind, source_id)

    def test_other_links_are_web_pages(self) -> None:
        result = classify_url("https://example.com/post")

        assert isinstance(result, SuccessResult)
        assert (result.value.kind, result.value.id.startswith("web-"), len(result.value.id)) == (
            SourceKind.WEB,
            True,
            16,
        )

    def test_youtube_id_is_the_video_id(self) -> None:
        result = classify_url("https://www.youtube.com/watch?v=abc123")

        assert isinstance(result, SuccessResult)
        assert result.value.id == "yt-abc123"

    def test_spotify_url_is_canonicalized(self) -> None:
        result = classify_url("https://open.spotify.com/episode/7ywcdUyAXA3dNFKU4xjFeY?si=x")

        assert isinstance(result, SuccessResult)
        assert result.value.url == "https://open.spotify.com/episode/7ywcdUyAXA3dNFKU4xjFeY"

    def test_web_id_is_stable_per_url(self) -> None:
        first = classify_url("https://example.com/a")
        second = classify_url("https://example.com/a")

        assert isinstance(first, SuccessResult)
        assert isinstance(second, SuccessResult)
        assert first.value.id == second.value.id

    @pytest.mark.parametrize(
        ("url", "message"),
        [
            ("ftp://example.com/x", "not an http(s) URL"),
            ("not a url", "not an http(s) URL"),
            ("https://www.youtube.com/@channel", "not a video"),
            ("https://www.youtube.com/watch", "not a video"),
            ("https://www.youtube.com/shorts/", "not a video"),
            ("https://youtu.be/bad$id", "not a video"),
            ("https://open.spotify.com/show/2MAi0BvDc6GTFvKFPXnkCL", "not an episode"),
        ],
    )
    def test_rejects_unsupported_links(self, url: str, message: str) -> None:
        result = classify_url(url)

        assert isinstance(result, ErrorResult)
        assert message in result.error


@pytest.fixture
def record() -> SourceRecord:
    return SourceRecord(
        id="yt-abc",
        kind=SourceKind.YOUTUBE,
        url="https://www.youtube.com/watch?v=abc",
        title="A  title\nsplit",
        author="Speaker",
        published="20261101",
        duration="3:01",
        description="Line one\nLine two",
        transcript="hello\nworld",
        metrics={"views": "1200"},
        measured_at="2026-11-17",
    )


@pytest.fixture
def written(record: SourceRecord, tmp_path: Path) -> RecordFiles:
    result = write_record(record=record, directory=tmp_path)
    assert isinstance(result, SuccessResult)
    return result.value


class TestWriteRecord:
    def test_writes_transcript(self, written: RecordFiles) -> None:
        assert written.text.read_text() == "hello\nworld\n"

    def test_meta_has_header_separator_and_description(self, written: RecordFiles) -> None:
        assert written.meta.read_text() == (
            "kind: youtube\n"
            "title: A title split\n"
            "author: Speaker\n"
            "url: https://www.youtube.com/watch?v=abc\n"
            "published: 20261101\n"
            "duration: 3:01\n"
            "views: 1200\n"
            "measured_at: 2026-11-17\n"
            "---\n"
            "Line one\nLine two\n"
        )

    def test_reports_line_count_and_transcript_presence(self, written: RecordFiles) -> None:
        assert written.to_dict() == {
            "id": "yt-abc",
            "kind": "youtube",
            "text": str(written.text),
            "meta": str(written.meta),
            "text_lines": 2,
            "has_transcript": True,
        }

    def test_marks_missing_transcript(self, record: SourceRecord, tmp_path: Path) -> None:
        bare = SourceRecord(id="web-x", kind=SourceKind.WEB, url="https://e.com", title="T")

        result = write_record(record=bare, directory=tmp_path)

        assert isinstance(result, SuccessResult)
        assert (result.value.has_transcript, result.value.text.read_text()) == (
            False,
            NO_TRANSCRIPT + "\n",
        )

    def test_rejects_unsafe_id(self, tmp_path: Path) -> None:
        bad = SourceRecord(id="../x", kind=SourceKind.WEB, url="https://e.com", title="T")

        result = write_record(record=bad, directory=tmp_path)

        assert isinstance(result, ErrorResult)

    def test_reports_unwritable_directory(self, record: SourceRecord, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x")

        result = write_record(record=record, directory=blocker / "sub")

        assert isinstance(result, ErrorResult)
        assert "cannot write record yt-abc" in result.error

    def test_defaults_to_workdir(
        self, record: SourceRecord, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

        result = write_record(record=record)

        assert isinstance(result, SuccessResult)
        assert result.value.text.parent == tmp_path / "Dev10x" / "kb" == workdir()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("abc_1-Z", True), ("abc\n", False), ("abc def", False), ("", False), ("../x", False)],
    ids=["plain", "trailing-newline", "space", "empty", "traversal"],
)
def test_is_safe_id(value: str, expected: bool) -> None:
    assert is_safe_id(value) is expected


def test_youtube_id_with_encoded_newline_is_not_a_video() -> None:
    result = classify_url("https://www.youtube.com/watch?v=abc%0A")

    assert isinstance(result, ErrorResult)
    assert "not a video" in result.error


class TestWorkDirSafety:
    def test_refuses_a_directory_another_user_owns(
        self, record: SourceRecord, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "work"
        target.mkdir()
        monkeypatch.setattr("os.getuid", lambda: target.stat().st_uid + 1)

        result = write_record(record=record, directory=target)

        assert isinstance(result, ErrorResult)
        assert "not this user" in result.error

    def test_closes_a_directory_others_can_write(
        self, record: SourceRecord, tmp_path: Path
    ) -> None:
        target = tmp_path / "work"
        target.mkdir()
        target.chmod(0o777)

        write_record(record=record, directory=target)

        assert target.stat().st_mode & 0o777 == 0o700

    def test_refuses_to_read_a_symlinked_meta(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret"
        secret.write_text("kind: web\n---\n")
        (tmp_path / "web-a.meta.txt").symlink_to(secret)

        result = read_meta(source_id="web-a", directory=tmp_path)

        assert isinstance(result, ErrorResult)
        assert "is a symlink" in result.error

    def test_creates_the_directory_private(self, record: SourceRecord, tmp_path: Path) -> None:
        target = tmp_path / "work"

        write_record(record=record, directory=target)

        assert target.stat().st_mode & 0o777 == 0o700

    @pytest.mark.parametrize("planted", ["yt-abc.txt", "yt-abc.meta.txt"])
    def test_refuses_a_planted_symlink(
        self, planted: str, record: SourceRecord, tmp_path: Path
    ) -> None:
        target = tmp_path / "work"
        target.mkdir()
        victim = tmp_path / "victim"
        victim.write_text("keep")
        (target / planted).symlink_to(victim)

        result = write_record(record=record, directory=target)

        assert isinstance(result, ErrorResult)
        assert ("is a symlink" in result.error, victim.read_text()) == (True, "keep")


class TestReadMeta:
    def test_reads_header_only(self, written: RecordFiles, tmp_path: Path) -> None:
        result = read_meta(source_id="yt-abc", directory=tmp_path)

        assert isinstance(result, SuccessResult)
        assert result.value["views"] == "1200"
        assert "Line one" not in result.value.values()

    def test_skips_lines_without_separator(self, tmp_path: Path) -> None:
        (tmp_path / "web-a.meta.txt").write_text("title: T\nnoise\n---\n")

        result = read_meta(source_id="web-a", directory=tmp_path)

        assert isinstance(result, SuccessResult)
        assert result.value == {"title": "T"}

    @pytest.mark.parametrize("source_id", ["missing", "../escape"])
    def test_rejects_missing_or_unsafe(self, source_id: str, tmp_path: Path) -> None:
        result = read_meta(source_id=source_id, directory=tmp_path)

        assert isinstance(result, ErrorResult)
