from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission.file_lock import locked_json_update


class TestLockedJsonUpdate:
    @pytest.fixture
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / ".claude" / "settings.local.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"permissions": {"allow": ["rule1"]}}, indent=2))
        return path

    def test_reads_existing_data(self, settings_file: Path) -> None:
        with locked_json_update(path=settings_file) as data:
            assert data["permissions"]["allow"] == ["rule1"]

    def test_writes_modified_data(self, settings_file: Path) -> None:
        with locked_json_update(path=settings_file) as data:
            data["permissions"]["allow"].append("rule2")

        result = json.loads(settings_file.read_text())
        assert "rule2" in result["permissions"]["allow"]

    def test_preserves_existing_data(self, settings_file: Path) -> None:
        with locked_json_update(path=settings_file) as data:
            data["permissions"]["allow"].append("rule2")

        result = json.loads(settings_file.read_text())
        assert "rule1" in result["permissions"]["allow"]

    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "new.json"

        with locked_json_update(path=path) as data:
            data["key"] = "value"

        result = json.loads(path.read_text())
        assert result["key"] == "value"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "settings.json"

        with locked_json_update(path=path) as data:
            data["created"] = True

        assert path.exists()

    def test_leaves_sidecar_in_place(self, settings_file: Path) -> None:
        # GH-77: lock sidecar is intentionally NOT unlinked on release.
        # Unlinking races: a third writer between unlink and the next
        # open(O_CREAT) gets a fresh inode and an independent flock,
        # breaking mutual exclusion.
        with locked_json_update(path=settings_file) as data:
            data["test"] = True

        lock_path = settings_file.with_suffix(".lock")
        assert lock_path.exists()

    def test_no_temp_files_left(self, settings_file: Path) -> None:
        parent = settings_file.parent
        before = set(parent.iterdir())

        with locked_json_update(path=settings_file) as data:
            data["test"] = True

        after = set(parent.iterdir())
        new_files = after - before
        temp_files = [f for f in new_files if ".tmp" in f.suffix]
        assert temp_files == []

    def test_atomic_write_on_error(self, settings_file: Path) -> None:
        original = settings_file.read_text()

        with pytest.raises(ValueError):
            with locked_json_update(path=settings_file) as data:
                data["permissions"]["allow"] = ["corrupted"]
                raise ValueError("simulated failure")

        assert settings_file.read_text() == original

    def test_formats_with_indent(self, settings_file: Path) -> None:
        with locked_json_update(path=settings_file) as data:
            data["new_key"] = True

        content = settings_file.read_text()
        assert "  " in content
        assert content.endswith("\n")
