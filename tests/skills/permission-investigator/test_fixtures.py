"""Tests for fixture materialization, snapshot, and rule mutation (GH-47)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission_investigator.fixtures import (
    apply_rule,
    materialize_fixtures,
    remove_rule,
    restore_settings,
    snapshot_settings,
)


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home" / "tester"
    home.mkdir(parents=True)
    return home


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "investigator-work"


class TestMaterializeFixtures:
    def test_creates_plugin_skill_file_under_home(
        self,
        workdir: Path,
        fake_home: Path,
    ) -> None:
        paths = materialize_fixtures(workdir=workdir, user_home=fake_home)

        assert paths.plugin_skill_file.is_file()
        assert paths.plugin_skill_file.is_relative_to(fake_home)
        assert paths.plugin_skill_file.read_text().startswith("# Probe")

    def test_creates_empty_project_settings_file(
        self,
        workdir: Path,
        fake_home: Path,
    ) -> None:
        paths = materialize_fixtures(workdir=workdir, user_home=fake_home)

        data = json.loads(paths.project_settings.read_text())

        assert data == {"permissions": {"allow": []}}

    def test_fixture_relpath_resolves_relative_to_home(
        self,
        workdir: Path,
        fake_home: Path,
    ) -> None:
        paths = materialize_fixtures(workdir=workdir, user_home=fake_home)

        assert (fake_home / paths.fixture_relpath).is_file()

    def test_cleanup_removes_workdir(
        self,
        workdir: Path,
        fake_home: Path,
    ) -> None:
        paths = materialize_fixtures(workdir=workdir, user_home=fake_home)

        paths.cleanup()

        assert not workdir.exists()

    def test_cleanup_removes_publisher_root_under_home(
        self,
        workdir: Path,
        fake_home: Path,
    ) -> None:
        paths = materialize_fixtures(workdir=workdir, user_home=fake_home)
        assert paths.publisher_root.is_dir()

        paths.cleanup()

        assert not paths.publisher_root.exists()
        assert not paths.fixture_root.exists()


class TestSnapshotAndRestore:
    def test_snapshot_returns_none_when_target_missing(self, tmp_path: Path) -> None:
        result = snapshot_settings(
            settings_path=tmp_path / "missing.json",
            snapshot_dir=tmp_path / "snaps",
        )

        assert result is None

    def test_snapshot_copies_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"permissions": {"allow": ["Bash(git log:*)"]}}')

        snap = snapshot_settings(
            settings_path=target,
            snapshot_dir=tmp_path / "snaps",
        )

        assert snap is not None
        assert snap.is_file()
        assert json.loads(snap.read_text()) == json.loads(target.read_text())

    def test_restore_overwrites_target_with_snapshot(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"permissions": {"allow": ["original"]}}')
        snap = snapshot_settings(
            settings_path=target,
            snapshot_dir=tmp_path / "snaps",
        )
        assert snap is not None
        target.write_text('{"permissions": {"allow": ["mutated"]}}')

        restore_settings(snapshot_path=snap, target_path=target)

        assert json.loads(target.read_text()) == {"permissions": {"allow": ["original"]}}


class TestApplyAndRemoveRule:
    def test_apply_rule_creates_file_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh-settings.json"

        apply_rule(rule="Read(~/x)", target=target)

        data = json.loads(target.read_text())
        assert data["permissions"]["allow"] == ["Read(~/x)"]

    def test_apply_rule_is_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"permissions": {"allow": ["Read(~/x)"]}}')

        apply_rule(rule="Read(~/x)", target=target)
        apply_rule(rule="Read(~/x)", target=target)

        data = json.loads(target.read_text())
        assert data["permissions"]["allow"].count("Read(~/x)") == 1

    def test_apply_rule_appends_new_rule(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"permissions": {"allow": ["Read(~/x)"]}}')

        apply_rule(rule="Bash(ls:*)", target=target)

        data = json.loads(target.read_text())
        assert data["permissions"]["allow"] == ["Read(~/x)", "Bash(ls:*)"]

    def test_remove_rule_drops_match(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"permissions": {"allow": ["Read(~/x)", "Bash(ls:*)"]}}')

        remove_rule(rule="Read(~/x)", target=target)

        data = json.loads(target.read_text())
        assert data["permissions"]["allow"] == ["Bash(ls:*)"]

    def test_remove_rule_is_noop_when_target_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "missing.json"

        remove_rule(rule="anything", target=target)

        assert not target.exists()
