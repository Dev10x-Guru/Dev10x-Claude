"""Tests for the legacy config.yaml -> friction.yaml migration (GH-812 R4)."""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.documents.session_yaml import (
    FrictionYamlDocument,
    SessionYamlDocument,
)
from dev10x.domain.friction_level import FrictionLevel
from dev10x.skills.permission import migrate_config as mod


def _write_config(*, root: Path, content: str) -> Path:
    path = root / ".claude" / "Dev10x" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _write_session(*, root: Path, content: str) -> Path:
    path = root / ".claude" / "Dev10x" / "session.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestDetect:
    def test_none_when_nothing_legacy(self, tmp_path: Path) -> None:
        assert mod.detect_legacy_config(root=tmp_path) is None

    def test_none_when_only_ephemeral_session(self, tmp_path: Path) -> None:
        # An ephemeral session.yaml (branch/tickets only) is not legacy.
        _write_session(root=tmp_path, content="branch: feature\ntickets: []\n")
        assert mod.detect_legacy_config(root=tmp_path) is None

    def test_finds_config_durable_prefs(self, tmp_path: Path) -> None:
        _write_config(root=tmp_path, content="friction_level: adaptive\n")
        finding = mod.detect_legacy_config(root=tmp_path)
        assert finding is not None
        assert finding["durable_prefs"] == {"friction_level": "adaptive"}
        assert finding["stale_files"] == [str(tmp_path / ".claude" / "Dev10x" / "config.yaml")]

    def test_pre_split_session_durable_keys_are_stale(self, tmp_path: Path) -> None:
        _write_session(root=tmp_path, content="friction_level: strict\n")
        finding = mod.detect_legacy_config(root=tmp_path)
        assert finding is not None
        assert finding["durable_prefs"] == {"friction_level": "strict"}
        assert str(tmp_path / ".claude" / "Dev10x" / "session.yaml") in finding["stale_files"]

    def test_config_removed_but_ephemeral_session_preserved(self, tmp_path: Path) -> None:
        _write_config(root=tmp_path, content="friction_level: guided\n")
        _write_session(root=tmp_path, content="branch: feature\n")
        finding = mod.detect_legacy_config(root=tmp_path)
        assert finding is not None
        session_path = str(tmp_path / ".claude" / "Dev10x" / "session.yaml")
        assert session_path not in finding["stale_files"]


class TestMigrateDryRun:
    def test_writes_nothing_and_returns_plan(self, tmp_path: Path) -> None:
        config_path = _write_config(root=tmp_path, content="friction_level: adaptive\n")
        result = mod.migrate_config_to_friction(root=tmp_path, dry_run=True)
        assert result["migrated"] is False
        assert result["dry_run"] is True
        assert result["prefs"] == {"friction_level": "adaptive"}
        assert "content" in result
        # Nothing written or removed.
        assert config_path.exists()
        assert not FrictionYamlDocument(toplevel=str(tmp_path)).path.exists()


class TestMigrateApply:
    def test_folds_into_friction_and_removes_config(self, tmp_path: Path) -> None:
        config_path = _write_config(
            root=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        result = mod.migrate_config_to_friction(root=tmp_path)
        assert result["migrated"] is True
        assert config_path.as_posix() in [Path(p).as_posix() for p in result["removed"]]
        assert not config_path.exists()
        # Prefs now resolve through friction.yaml.
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_no_legacy_is_noop(self, tmp_path: Path) -> None:
        result = mod.migrate_config_to_friction(root=tmp_path)
        assert result == {
            "migrated": False,
            "reason": "no legacy config found",
            "removed": [],
        }

    def test_idempotent_single_entry(self, tmp_path: Path) -> None:
        _write_config(root=tmp_path, content="friction_level: adaptive\n")
        mod.migrate_config_to_friction(root=tmp_path)
        # Re-create the legacy file and migrate again — must not duplicate.
        _write_config(root=tmp_path, content="friction_level: strict\n")
        mod.migrate_config_to_friction(root=tmp_path)
        doc = FrictionYamlDocument(toplevel=str(tmp_path))._doc()
        matching = [
            entry
            for entry in doc["projects"]
            if entry["match"] == FrictionYamlDocument.match_globs_for(str(tmp_path))
        ]
        assert len(matching) == 1
        assert matching[0]["friction_level"] == "strict"

    def test_removes_durable_session_too(self, tmp_path: Path) -> None:
        session_path = _write_session(root=tmp_path, content="friction_level: strict\n")
        result = mod.migrate_config_to_friction(root=tmp_path)
        assert result["migrated"] is True
        assert not session_path.exists()

    def test_preserves_existing_defaults(self, tmp_path: Path) -> None:
        friction = FrictionYamlDocument(toplevel=str(tmp_path))
        friction.path.parent.mkdir(parents=True, exist_ok=True)
        friction.path.write_text("defaults:\n  friction_level: guided\n")
        _write_config(root=tmp_path, content="active_modes: [solo-maintainer]\n")
        mod.migrate_config_to_friction(root=tmp_path)
        doc = friction._doc()
        assert doc["defaults"] == {"friction_level": "guided"}
        assert doc["projects"][0]["active_modes"] == ["solo-maintainer"]

    def test_parity_failure_leaves_stale_files(self, tmp_path: Path, monkeypatch) -> None:
        config_path = _write_config(root=tmp_path, content="friction_level: adaptive\n")
        monkeypatch.setattr(FrictionYamlDocument, "matched", lambda self: None)
        result = mod.migrate_config_to_friction(root=tmp_path)
        assert "error" in result
        assert config_path.exists()


class TestParity:
    def test_false_when_matched_none(self) -> None:
        assert mod._parity(matched=None, prefs={"friction_level": "adaptive"}) is False

    def test_false_on_mismatch(self) -> None:
        assert (
            mod._parity(matched={"friction_level": "guided"}, prefs={"friction_level": "adaptive"})
            is False
        )

    def test_true_when_all_match(self) -> None:
        assert (
            mod._parity(
                matched={"friction_level": "adaptive", "active_modes": []},
                prefs={"friction_level": "adaptive"},
            )
            is True
        )


class TestLoadSessionMapping:
    def test_empty_when_missing(self, tmp_path: Path) -> None:
        assert mod._load_session_mapping(root=tmp_path) == {}

    def test_empty_when_malformed(self, tmp_path: Path) -> None:
        _write_session(root=tmp_path, content="friction_level: [oops\n")
        assert mod._load_session_mapping(root=tmp_path) == {}

    def test_empty_when_not_a_mapping(self, tmp_path: Path) -> None:
        _write_session(root=tmp_path, content="- a\n- b\n")
        assert mod._load_session_mapping(root=tmp_path) == {}
