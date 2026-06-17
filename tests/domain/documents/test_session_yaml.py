"""Tests for SessionYamlDocument (GH-515 / GH-513).

The Document owns the session.yaml read so Policy Rules stay I/O-free
(ADR-0007 D3). These cover the soft-fallback behaviour the rules used to
own: missing file, malformed YAML, and non-mapping / non-list values.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.documents.session_yaml import SessionYamlDocument
from dev10x.domain.friction_level import FrictionLevel


def _write(*, tmp_path: Path, content: str) -> str:
    (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
    (tmp_path / ".claude" / "Dev10x" / "session.yaml").write_text(content)
    return str(tmp_path)


class TestPath:
    def test_resolves_under_claude_dev10x(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        assert doc.path == tmp_path / ".claude" / "Dev10x" / "session.yaml"


class TestReadFrictionLevel:
    def test_reads_declared_level(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="friction_level: adaptive\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.ADAPTIVE
        )

    def test_defaults_when_file_missing(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        assert doc.read_friction_level() is FrictionLevel.default()

    def test_defaults_when_malformed(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="friction_level: adaptive\nmodes: [a\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.default()
        )

    def test_defaults_when_unknown_value(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="friction_level: bananas\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.default()
        )

    def test_defaults_when_top_level_not_mapping(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="- just\n- a\n- list\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.default()
        )

    def test_defaults_when_file_undecodable(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
        (tmp_path / ".claude" / "Dev10x" / "session.yaml").write_bytes(b"\xff\xfe\x00bad")
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        assert doc.read_friction_level() is FrictionLevel.default()


class TestReadActiveModes:
    def test_reads_declared_modes(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="active_modes: [solo-maintainer]\n")
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == ["solo-maintainer"]

    def test_empty_when_unset(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="friction_level: adaptive\n")
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == []

    def test_empty_when_not_a_list(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="active_modes: solo-maintainer\n")
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == []

    def test_empty_when_file_missing(self, tmp_path: Path) -> None:
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_active_modes() == []


class TestReadFrictionAndModes:
    def test_reads_both(self, tmp_path: Path) -> None:
        toplevel = _write(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        level, modes = SessionYamlDocument(toplevel=toplevel).read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_falls_back_when_file_missing(self, tmp_path: Path) -> None:
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.default()
        assert modes == []

    def test_modes_empty_when_not_a_list(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="friction_level: guided\nactive_modes: 3\n")
        level, modes = SessionYamlDocument(toplevel=toplevel).read_friction_and_modes()
        assert level is FrictionLevel.GUIDED
        assert modes == []
