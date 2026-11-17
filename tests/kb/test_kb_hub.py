"""The URL-keyed hub table (GH-1985)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.core.domain.file_locks import LockTimeoutError
from dev10x.kb import hub
from dev10x.kb.config import KbConfig
from dev10x.kb.hub import HubAction, HubWrite, build_row, reach, upsert_hub_row
from dev10x.kb.record import SourceRecord

ROW = (
    "| 2026-11-17 | youtube | Jane Doe | [Talk](https://www.youtube.com/watch?v=vid1) "
    "| hook->list | 12.0k views · 1.2k/day · 5.0% eng · 5.0k subs · 10 d "
    "| [2026-11-17](../2026/2026-11-17.md) |"
)


@pytest.fixture
def note(vault: Path) -> Path:
    path = vault / "2026" / "2026-11-17.md"
    path.parent.mkdir()
    path.write_text("# day\n")
    return path


def _upsert(
    config: KbConfig, note: Path, records: Path, structure: str = "hook->list"
) -> HubWrite:
    result = upsert_hub_row(
        config=config,
        source_id="yt-vid1",
        name="Jane Doe - Talk",
        structure=structure,
        note=note,
        directory=records,
    )
    assert isinstance(result, SuccessResult), result
    return result.value


class TestUpsert:
    def test_creates_hub_with_frontmatter_table_and_vocabulary(
        self, kb_config: KbConfig, note: Path, records: Path, youtube_record: SourceRecord
    ) -> None:
        written = _upsert(kb_config, note, records)

        text = (kb_config.hub or Path()).read_text()
        assert written.action is HubAction.CREATED
        assert text.startswith("---\ntype: Hub\n")
        assert f"{hub.DIVIDER}\n{ROW}\n" in text
        assert text.endswith(hub.VOCABULARY)

    def test_refreshes_existing_row_in_place(
        self, kb_config: KbConfig, note: Path, records: Path, youtube_record: SourceRecord
    ) -> None:
        _upsert(kb_config, note, records)

        written = _upsert(kb_config, note, records, structure="hook->story")

        text = (kb_config.hub or Path()).read_text()
        assert written.action is HubAction.REFRESHED
        assert (text.count("watch?v=vid1"), "hook->story" in text) == (1, True)

    def test_appends_after_the_last_table_row(
        self, kb_config: KbConfig, note: Path, records: Path, youtube_record: SourceRecord
    ) -> None:
        hub_path = kb_config.hub or Path()
        hub_path.parent.mkdir(parents=True)
        hub_path.write_text(
            "---\ntitle: H\ngenerated: old\n---\n\n"
            f"{hub.HEADER}\n{hub.DIVIDER}\n| a | b |\n\n## Structure vocabulary\n"
        )

        written = _upsert(kb_config, note, records)

        lines = hub_path.read_text().splitlines()
        assert written.action is HubAction.APPENDED
        assert lines[7:9] == ["| a | b |", ROW]
        assert lines[2].startswith("generated: { by: process:dev10x-kb")

    def test_adds_a_table_to_a_hub_without_one(
        self, kb_config: KbConfig, note: Path, records: Path, youtube_record: SourceRecord
    ) -> None:
        hub_path = kb_config.hub or Path()
        hub_path.parent.mkdir(parents=True)
        hub_path.write_text("# Hub\n")

        _upsert(kb_config, note, records)

        assert hub_path.read_text() == f"# Hub\n\n{hub.HEADER}\n{hub.DIVIDER}\n{ROW}\n"

    def test_leaves_other_tables_untouched(
        self, kb_config: KbConfig, note: Path, records: Path, youtube_record: SourceRecord
    ) -> None:
        hub_path = kb_config.hub or Path()
        hub_path.parent.mkdir(parents=True)
        vocabulary = "## Structure vocabulary\n\n| Label | Meaning |\n|---|---|\n| hook | x |\n"
        hub_path.write_text(f"{hub.HEADER}\n{hub.DIVIDER}\n| old | row |\n\n{vocabulary}")

        _upsert(kb_config, note, records)

        assert hub_path.read_text() == (
            f"{hub.HEADER}\n{hub.DIVIDER}\n| old | row |\n{ROW}\n\n{vocabulary}"
        )

    def test_matches_rows_only_by_their_title_url(
        self, kb_config: KbConfig, note: Path, records: Path, youtube_record: SourceRecord
    ) -> None:
        hub_path = kb_config.hub or Path()
        hub_path.parent.mkdir(parents=True)
        decoy = (
            "| d | web | A | [Other](https://o.com) "
            "| see ](https://www.youtube.com/watch?v=vid1) | r | n |"
        )
        hub_path.write_text(f"{hub.HEADER}\n{hub.DIVIDER}\n{decoy}\n")

        written = _upsert(kb_config, note, records)

        assert written.action is HubAction.APPENDED
        assert hub_path.read_text().splitlines()[2:] == [decoy, ROW]

    def test_skips_without_a_hub(self, kb_config: KbConfig, note: Path, records: Path) -> None:
        written = _upsert(replace(kb_config, hub=None), note, records)

        assert written.to_dict() == {
            "path": None,
            "action": "skipped",
            "reason": "no `kb.hub` configured",
        }

    @pytest.mark.parametrize(
        ("name", "structure", "note_name", "message"),
        [
            ("A\nB", "s", "2026/2026-11-17.md", "must be single lines"),
            ("A - B", "s\nt", "2026/2026-11-17.md", "must be single lines"),
            ("A - B", "s", "/outside.md", "is outside the vault"),
            ("A - B", "s", "2026/2026-11-17.md", "run `dev10x skill kb fetch` first"),
        ],
        ids=["multiline-name", "multiline-structure", "note-outside-vault", "record-missing"],
    )
    def test_rejects_bad_input(
        self,
        name: str,
        structure: str,
        note_name: str,
        message: str,
        kb_config: KbConfig,
        vault: Path,
        records: Path,
    ) -> None:
        result = upsert_hub_row(
            config=kb_config,
            source_id="yt-vid1",
            name=name,
            structure=structure,
            note=vault / note_name,
            directory=records,
        )

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_refuses_symlinked_hub(
        self,
        kb_config: KbConfig,
        note: Path,
        records: Path,
        youtube_record: SourceRecord,
        tmp_path: Path,
    ) -> None:
        hub_path = kb_config.hub or Path()
        hub_path.parent.mkdir(parents=True)
        (tmp_path / "elsewhere.md").write_text("x")
        hub_path.symlink_to(tmp_path / "elsewhere.md")

        result = upsert_hub_row(
            config=kb_config,
            source_id="yt-vid1",
            name="A - B",
            structure="s",
            note=note,
            directory=records,
        )

        assert isinstance(result, ErrorResult)
        assert "symlink" in result.error

    @pytest.mark.parametrize(
        ("error", "message"),
        [(LockTimeoutError("locked"), "locked"), (OSError("disk full"), "disk full")],
        ids=["lock-timeout", "os-error"],
    )
    def test_reports_write_failures(
        self,
        error: Exception,
        message: str,
        kb_config: KbConfig,
        note: Path,
        records: Path,
        youtube_record: SourceRecord,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def explode(*_: object) -> None:
            raise error

        monkeypatch.setattr(hub, "atomic_write_text", explode)

        result = upsert_hub_row(
            config=kb_config,
            source_id="yt-vid1",
            name="A - B",
            structure="s",
            note=note,
            directory=records,
        )

        assert isinstance(result, ErrorResult)
        assert message in result.error


class TestReach:
    @pytest.mark.parametrize(
        ("meta", "expected"),
        [
            (
                {
                    "kind": "youtube",
                    "views": "2500000",
                    "likes": "",
                    "channel_subs": "0",
                    "published": "bad",
                    "measured_at": "2026-11-17",
                },
                "2.5M views · 2.5M/day · — eng · — subs · 1 d",
            ),
            (
                {"kind": "youtube", "views": "", "published": "", "measured_at": ""},
                "— views · —/day · — eng · — subs · 1 d",
            ),
            (
                {"kind": "youtube", "views": "500", "likes": "5", "measured_at": "2026-11-17"},
                "500 views · 500/day · 1.0% eng · — subs · 1 d",
            ),
            ({"kind": "spotify", "duration": "1:02:05", "show": "Pod"}, "1:02:05 · Pod"),
            ({"kind": "web", "site": "Blog", "words": "900"}, "Blog · 900 words"),
            ({"kind": "web", "site": "", "words": ""}, ""),
        ],
    )
    def test_formats_reach_per_kind(self, meta: dict[str, str], expected: str) -> None:
        assert reach(meta) == expected


def test_row_without_speaker_uses_author_and_escapes_pipes() -> None:
    row = build_row(
        meta={"kind": "web", "author": "Blog", "url": "https://e.com", "measured_at": "d"},
        name="Plain title",
        structure="a|b",
        note_link="[n](n.md)",
    )

    assert row.render() == (
        "| d | web | Blog | [Plain title](https://e.com) | a\\|b |  | [n](n.md) |"
    )


def test_row_encodes_pipes_in_the_url() -> None:
    row = build_row(
        meta={"kind": "web", "url": "https://e.com/?a=1|2", "measured_at": "d"},
        name="T",
        structure="s",
        note_link="[n](n.md)",
    )

    assert row.render().split(" | ")[3] == "[T](https://e.com/?a=1%7C2)"


class TestHubEncoding:
    def test_reports_a_hub_that_is_not_utf8(
        self, kb_config: KbConfig, note: Path, records: Path, youtube_record: SourceRecord
    ) -> None:
        hub_path = kb_config.hub or Path()
        hub_path.parent.mkdir(parents=True)
        hub_path.write_bytes(b"\xff\xfe broken")

        result = upsert_hub_row(
            config=kb_config,
            source_id="yt-vid1",
            name="A - B",
            structure="s",
            note=note,
            directory=records,
        )

        assert isinstance(result, ErrorResult)
        assert "is not valid UTF-8" in result.error


def test_row_escapes_links_backslashes_and_line_breaks() -> None:
    row = build_row(
        meta={"kind": "web", "url": "https://e.com/a b(c)", "measured_at": "d"},
        name="Ann - Talk [live]\r",
        structure="a\\|b\rc",
        note_link="[n](n.md)",
    )

    assert row.render() == (
        "| d | web | Ann | [Talk \\[live\\]](https://e.com/a%20b%28c%29) "
        "| a\\\\\\|b c |  | [n](n.md) |"
    )
