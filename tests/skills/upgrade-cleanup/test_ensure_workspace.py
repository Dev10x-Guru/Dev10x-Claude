"""Tests for ensure_workspace_directories (GH-40)."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission.update_paths import (
    _ensure_workspace,
    ensure_workspace_directories,
)


class TestEnsureWorkspaceDirectories:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"allow": []}}))
        return path

    def test_adds_missing_directory(self, settings_file: Path) -> None:
        count, messages = ensure_workspace_directories(
            settings_file,
            ["/tmp/Dev10x"],
        )

        assert count == 1
        assert any("/tmp/Dev10x" in m for m in messages)
        data = json.loads(settings_file.read_text())
        assert data["permissions"]["additionalDirectories"] == ["/tmp/Dev10x"]

    def test_skips_already_present_directory(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [],
                        "additionalDirectories": ["/tmp/Dev10x"],
                    }
                }
            )
        )

        count, messages = ensure_workspace_directories(
            settings_file,
            ["/tmp/Dev10x"],
        )

        assert count == 0
        assert messages == []

    def test_appends_to_existing_directories(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [],
                        "additionalDirectories": ["/tmp/something-else"],
                    }
                }
            )
        )

        count, _ = ensure_workspace_directories(
            settings_file,
            ["/tmp/Dev10x"],
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        assert "/tmp/something-else" in data["permissions"]["additionalDirectories"]
        assert "/tmp/Dev10x" in data["permissions"]["additionalDirectories"]

    def test_dry_run_does_not_modify_file(self, settings_file: Path) -> None:
        original = settings_file.read_text()

        count, messages = ensure_workspace_directories(
            settings_file,
            ["/tmp/Dev10x"],
            dry_run=True,
        )

        assert count == 1
        assert messages
        assert settings_file.read_text() == original

    def test_handles_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not valid json")

        count, messages = ensure_workspace_directories(
            path,
            ["/tmp/Dev10x"],
        )

        assert count == 0
        assert any("invalid JSON" in m for m in messages)

    def test_creates_permissions_section_if_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({}))

        count, _ = ensure_workspace_directories(path, ["/tmp/Dev10x"])

        assert count == 1
        data = json.loads(path.read_text())
        assert data["permissions"]["additionalDirectories"] == ["/tmp/Dev10x"]


class TestEnsureWorkspaceOrchestrator:
    @pytest.fixture()
    def two_files(self, tmp_path: Path) -> list[Path]:
        f1 = tmp_path / "a" / "settings.local.json"
        f2 = tmp_path / "b" / "settings.local.json"
        for f in (f1, f2):
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps({"permissions": {"allow": []}}))
        return [f1, f2]

    def test_processes_all_files(
        self,
        two_files: list[Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = _ensure_workspace(
            config={"workspace_directories": ["/tmp/Dev10x"]},
            settings_files=two_files,
            dry_run=False,
            quiet=True,
        )

        assert rc == 0
        for path in two_files:
            data = json.loads(path.read_text())
            assert data["permissions"]["additionalDirectories"] == ["/tmp/Dev10x"]

    def test_returns_zero_when_no_workspace_dirs_configured(
        self,
        two_files: list[Path],
    ) -> None:
        rc = _ensure_workspace(
            config={},
            settings_files=two_files,
            dry_run=False,
            quiet=True,
        )

        assert rc == 0
        for path in two_files:
            data = json.loads(path.read_text())
            assert "additionalDirectories" not in data.get("permissions", {})
