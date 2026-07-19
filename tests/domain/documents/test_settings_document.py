"""Tests for SettingsDocument — D3 / ADR-0007 I/O extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.documents.settings_document import (
    SettingsDocument,
    _deduplicate_rules,
    _migrate_rules,
)

REPLACEMENTS = [("/old/v1/", "/new/v2/")]


@pytest.fixture()
def settings_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_rewrites_allow_and_deny(settings_path: Path) -> None:
    _write(
        settings_path,
        {
            "permissions": {
                "allow": ["Bash(/old/v1/run.sh:*)"],
                "deny": ["Read(/old/v1/secret)"],
            }
        },
    )

    migrated = SettingsDocument(path=settings_path).apply_replacements(replacements=REPLACEMENTS)

    written = json.loads(settings_path.read_text())
    assert migrated == 2
    assert written["permissions"]["allow"] == ["Bash(/new/v2/run.sh:*)"]
    assert written["permissions"]["deny"] == ["Read(/new/v2/secret)"]


def test_deduplicates_after_rewrite(settings_path: Path) -> None:
    _write(
        settings_path,
        {"permissions": {"allow": ["Bash(/old/v1/x)", "Bash(/new/v2/x)"]}},
    )

    migrated = SettingsDocument(path=settings_path).apply_replacements(replacements=REPLACEMENTS)

    written = json.loads(settings_path.read_text())
    assert migrated == 1
    assert written["permissions"]["allow"] == ["Bash(/new/v2/x)"]


def test_no_match_returns_zero_and_leaves_file_unchanged(settings_path: Path) -> None:
    original = json.dumps({"permissions": {"allow": ["Bash(/other/run.sh)"]}}, indent=2) + "\n"
    settings_path.write_text(original)

    migrated = SettingsDocument(path=settings_path).apply_replacements(replacements=REPLACEMENTS)

    assert migrated == 0
    assert settings_path.read_text() == original


def test_missing_permissions_key_returns_zero(settings_path: Path) -> None:
    _write(settings_path, {"model": "opus"})

    migrated = SettingsDocument(path=settings_path).apply_replacements(replacements=REPLACEMENTS)

    assert migrated == 0


def test_invalid_json_raises(settings_path: Path) -> None:
    settings_path.write_text("{not valid json")

    with pytest.raises(json.JSONDecodeError):
        SettingsDocument(path=settings_path).apply_replacements(replacements=REPLACEMENTS)


def test_preview_replacements_does_not_write(settings_path: Path) -> None:
    original = json.dumps({"permissions": {"allow": ["Bash(/old/v1/x)"]}}, indent=2) + "\n"
    settings_path.write_text(original)

    new_content, count = SettingsDocument(path=settings_path).preview_replacements(
        replacements=REPLACEMENTS
    )

    assert count == 1
    assert new_content is not None
    assert "/new/v2/" in new_content
    # The on-disk file is untouched by the dry-run pass.
    assert settings_path.read_text() == original


def test_preview_replacements_returns_none_when_unchanged(settings_path: Path) -> None:
    _write(settings_path, {"permissions": {"allow": ["Bash(/other/run.sh)"]}})

    new_content, count = SettingsDocument(path=settings_path).preview_replacements(
        replacements=REPLACEMENTS
    )

    assert count == 0
    assert new_content is None


def test_preview_replacements_raises_on_bad_json(settings_path: Path) -> None:
    settings_path.write_text("{not valid json")

    with pytest.raises(json.JSONDecodeError):
        SettingsDocument(path=settings_path).preview_replacements(replacements=REPLACEMENTS)


def test_apply_reads_fresh_state_not_stale_preview(settings_path: Path) -> None:
    # GH-825: a preview snapshot must never be persisted directly. When a
    # concurrent writer edits the file after the dry-run preview, the apply
    # pass re-reads under the lock, so the concurrent edit survives and the
    # migration still applies.
    _write(settings_path, {"permissions": {"allow": ["Bash(/old/v1/x)"]}})
    doc = SettingsDocument(path=settings_path)
    doc.preview_replacements(replacements=REPLACEMENTS)  # stale snapshot, discarded

    _write(settings_path, {"permissions": {"allow": ["Bash(/old/v1/x)", "Bash(/keep/me)"]}})

    migrated = doc.apply_replacements(replacements=REPLACEMENTS)

    allow = json.loads(settings_path.read_text())["permissions"]["allow"]
    assert migrated == 1
    assert "Bash(/new/v2/x)" in allow
    assert "Bash(/keep/me)" in allow


def test_migrate_rules_counts_each_rewrite() -> None:
    result, count = _migrate_rules(
        rules=["/old/a", "/old/b", "/keep/c"], replacements=REPLACEMENTS
    )

    assert count == 0
    assert result == ["/old/a", "/old/b", "/keep/c"]


def test_migrate_rules_applies_first_matching_replacement() -> None:
    result, count = _migrate_rules(
        rules=["x /old/v1/ y"],
        replacements=REPLACEMENTS,
    )

    assert count == 1
    assert result == ["x /new/v2/ y"]


def test_deduplicate_rules_preserves_order() -> None:
    assert _deduplicate_rules(rules=["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
