"""Copying a fetched record into the vault (GH-1985)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.core.domain.knowledge_vault import VaultConfig
from dev10x.kb.config import KbConfig
from dev10x.kb.persist import persist_record, validate_name
from dev10x.kb.record import SourceKind, SourceRecord, write_record


def test_copies_text_and_meta_under_readable_names(
    kb_config: KbConfig, vault: Path, records: Path, youtube_record: SourceRecord
) -> None:
    dest = vault / "2026" / "Attachments"

    result = persist_record(
        config=kb_config,
        source_id="yt-vid1",
        attachments=dest,
        name="Jane  Doe - Talk",
        directory=records,
    )

    assert isinstance(result, SuccessResult)
    assert (result.value.text.name, result.value.text.read_text()) == (
        "Jane Doe - Talk - transcript.txt",
        "spoken\n",
    )
    assert result.value.to_dict()["meta"] == str(dest / "Jane Doe - Talk - meta.txt")


def test_web_text_is_saved_as_markdown(kb_config: KbConfig, vault: Path, records: Path) -> None:
    page = SourceRecord(id="web-1", kind=SourceKind.WEB, url="https://e.com", title="P")
    assert isinstance(write_record(record=page, directory=records), SuccessResult)

    result = persist_record(
        config=kb_config, source_id="web-1", attachments=vault, name="Site - P", directory=records
    )

    assert isinstance(result, SuccessResult)
    assert result.value.text.name == "Site - P - article.md"


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "non-empty"),
        ("  ", "non-empty"),
        (".hidden", "not start with '.'"),
        ("a/b", "path, link or control character"),
        ("What? - Now", "path, link or control character"),
        ("x [y]", "path, link or control character"),
        ("bell\x07 - title", "path, link or control character"),
        ("x" * 151, "longer than 150 characters"),
    ],
)
def test_rejects_unsafe_names(name: str, message: str) -> None:
    result = validate_name(name)

    assert isinstance(result, ErrorResult)
    assert message in result.error


def test_refuses_to_write_through_a_symlink(
    kb_config: KbConfig, vault: Path, records: Path, youtube_record: SourceRecord, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    (vault / "A - B - transcript.txt").symlink_to(outside)

    result = persist_record(
        config=kb_config, source_id="yt-vid1", attachments=vault, name="A - B", directory=records
    )

    assert isinstance(result, ErrorResult)
    assert ("is a symlink" in result.error, outside.read_text()) == (True, "keep")


def test_refuses_to_copy_a_symlinked_source(
    kb_config: KbConfig, vault: Path, records: Path, youtube_record: SourceRecord, tmp_path: Path
) -> None:
    secret = tmp_path / "secret"
    secret.write_text("private")
    (records / "yt-vid1.txt").unlink()
    (records / "yt-vid1.txt").symlink_to(secret)

    result = persist_record(
        config=kb_config, source_id="yt-vid1", attachments=vault, name="A - B", directory=records
    )

    assert isinstance(result, ErrorResult)
    assert "yt-vid1.txt is a symlink" in result.error
    assert list(vault.iterdir()) == []


def test_refuses_record_of_unknown_kind(kb_config: KbConfig, vault: Path, records: Path) -> None:
    records.mkdir(parents=True, exist_ok=True)
    (records / "web-x.meta.txt").write_text("kind: podcast\n---\n")

    result = persist_record(
        config=kb_config, source_id="web-x", attachments=vault, name="A - B", directory=records
    )

    assert isinstance(result, ErrorResult)
    assert "unknown kind 'podcast'" in result.error


def test_persist_refuses_unsafe_name(kb_config: KbConfig, vault: Path, records: Path) -> None:
    result = persist_record(
        config=kb_config, source_id="yt-vid1", attachments=vault, name="a/../x", directory=records
    )

    assert isinstance(result, ErrorResult)
    assert "path, link or control character" in result.error


@pytest.mark.parametrize(
    ("dest", "message"),
    [
        ("relative/dir", "must be an absolute path inside the vault"),
        ("/elsewhere", "is outside the vault"),
    ],
)
def test_refuses_destinations_outside_the_vault(
    dest: str, message: str, kb_config: KbConfig, records: Path, youtube_record: SourceRecord
) -> None:
    result = persist_record(
        config=kb_config,
        source_id="yt-vid1",
        attachments=Path(dest),
        name="A - B",
        directory=records,
    )

    assert isinstance(result, ErrorResult)
    assert message in result.error


def test_refuses_without_a_vault(records: Path, vault: Path) -> None:
    unconfigured = KbConfig(vault=VaultConfig(source="t", configured=False, reason="no vault"))

    result = persist_record(
        config=unconfigured,
        source_id="yt-vid1",
        attachments=vault,
        name="A - B",
        directory=records,
    )

    assert isinstance(result, ErrorResult)
    assert result.error == "no vault"


def test_requires_a_fetched_record(kb_config: KbConfig, vault: Path, records: Path) -> None:
    result = persist_record(
        config=kb_config, source_id="yt-none", attachments=vault, name="A - B", directory=records
    )

    assert isinstance(result, ErrorResult)
    assert "run `dev10x skill kb fetch` first" in result.error


def test_reports_unwritable_destination(
    kb_config: KbConfig, vault: Path, records: Path, youtube_record: SourceRecord
) -> None:
    (vault / "file").write_text("x")

    result = persist_record(
        config=kb_config,
        source_id="yt-vid1",
        attachments=vault / "file" / "sub",
        name="A - B",
        directory=records,
    )

    assert isinstance(result, ErrorResult)
    assert "cannot persist yt-vid1" in result.error
