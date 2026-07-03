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


class TestRender:
    """GH-584 N19: the Document owns the session.yaml template (write side)."""

    def test_defaults_to_guided_empty_modes(self) -> None:
        body = SessionYamlDocument.render()
        assert "friction_level: guided  # strict | guided | adaptive" in body
        assert "active_modes: []" in body

    def test_renders_chosen_level_and_modes(self) -> None:
        body = SessionYamlDocument.render(
            friction_level="adaptive", active_modes=["solo-maintainer"]
        )
        assert "friction_level: adaptive" in body
        assert "active_modes: ['solo-maintainer']" in body

    def test_round_trips_through_reader(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
        doc.path.write_text(SessionYamlDocument.render(friction_level="strict"))
        assert doc.read_friction_level() is FrictionLevel.STRICT


class TestWrite:
    def test_creates_parents_and_writes(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        doc.write(friction_level="adaptive", active_modes=["solo-maintainer"])
        level, modes = doc.read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_write_defaults(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        doc.write()
        level, modes = doc.read_friction_and_modes()
        assert level is FrictionLevel.GUIDED
        assert modes == []


class TestReadSessionIdentity:
    """ADR-0016 #753: recorded identity feeds the session_stale predicate."""

    def test_reads_branch_and_tickets(self, tmp_path: Path) -> None:
        toplevel = _write(
            tmp_path=tmp_path,
            content="branch: user/GH-1/x\ntickets: [GH-1, GH-2]\n",
        )
        identity = SessionYamlDocument(toplevel=toplevel).read_session_identity()
        assert identity == {"branch": "user/GH-1/x", "tickets": ["GH-1", "GH-2"]}

    def test_missing_file_yields_identity_less(self, tmp_path: Path) -> None:
        identity = SessionYamlDocument(toplevel=str(tmp_path)).read_session_identity()
        assert identity == {"branch": None, "tickets": []}

    def test_invalid_shapes_degrade(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="branch: [a]\ntickets: nope\n")
        identity = SessionYamlDocument(toplevel=toplevel).read_session_identity()
        assert identity == {"branch": None, "tickets": []}

    def test_non_string_tickets_filtered(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="tickets: [GH-1, 3, GH-2]\n")
        identity = SessionYamlDocument(toplevel=toplevel).read_session_identity()
        assert identity["tickets"] == ["GH-1", "GH-2"]
