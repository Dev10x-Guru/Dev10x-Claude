"""Tests for the split session config documents (GH-774, GH-515 / GH-513).

Durable prefs live in ``config.yaml`` (:class:`ConfigYamlDocument`);
ephemeral per-worktree state in ``session.yaml``
(:class:`SessionYamlDocument`). ``SessionYamlDocument`` stays the read
facade — its durable readers prefer ``config.yaml`` and fall back to a
pre-split ``session.yaml`` (the migration path). These cover the
soft-fallback behaviour the rules used to own (ADR-0007 D3): missing
file, malformed YAML, non-mapping / non-list values.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.documents.session_yaml import ConfigYamlDocument, SessionYamlDocument
from dev10x.domain.friction_level import FrictionLevel


def _write(*, tmp_path: Path, content: str) -> str:
    """Write a pre-split ``session.yaml`` (durable keys — migration path)."""
    (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
    (tmp_path / ".claude" / "Dev10x" / "session.yaml").write_text(content)
    return str(tmp_path)


def _write_config(*, tmp_path: Path, content: str) -> str:
    """Write ``config.yaml`` (durable prefs, the post-GH-774 home)."""
    (tmp_path / ".claude" / "Dev10x").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "Dev10x" / "config.yaml").write_text(content)
    return str(tmp_path)


class TestPath:
    def test_session_resolves_under_claude_dev10x(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        assert doc.path == tmp_path / ".claude" / "Dev10x" / "session.yaml"

    def test_config_resolves_under_claude_dev10x(self, tmp_path: Path) -> None:
        doc = ConfigYamlDocument(toplevel=str(tmp_path))
        assert doc.path == tmp_path / ".claude" / "Dev10x" / "config.yaml"


class TestReadFrictionLevel:
    def test_reads_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: adaptive\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.ADAPTIVE
        )

    def test_falls_back_to_pre_split_session(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="friction_level: adaptive\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.ADAPTIVE
        )

    def test_config_wins_over_session_fallback(self, tmp_path: Path) -> None:
        _write(tmp_path=tmp_path, content="friction_level: adaptive\n")
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: strict\n")
        assert SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.STRICT

    def test_defaults_when_both_missing(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        assert doc.read_friction_level() is FrictionLevel.default()

    def test_defaults_when_malformed(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path, content="friction_level: adaptive\nmodes: [a\n"
        )
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.default()
        )

    def test_defaults_when_unknown_value(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: bananas\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.default()
        )

    def test_defaults_when_top_level_not_mapping(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="- just\n- a\n- list\n")
        assert (
            SessionYamlDocument(toplevel=toplevel).read_friction_level() is FrictionLevel.default()
        )

    def test_defaults_when_file_undecodable(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
        (tmp_path / ".claude" / "Dev10x" / "config.yaml").write_bytes(b"\xff\xfe\x00bad")
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        assert doc.read_friction_level() is FrictionLevel.default()


class TestReadActiveModes:
    def test_reads_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="active_modes: [solo-maintainer]\n")
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == ["solo-maintainer"]

    def test_falls_back_to_pre_split_session(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="active_modes: [solo-maintainer]\n")
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == ["solo-maintainer"]

    def test_empty_when_unset(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: adaptive\n")
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == []

    def test_empty_when_not_a_list(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="active_modes: solo-maintainer\n")
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == []

    def test_empty_when_both_missing(self, tmp_path: Path) -> None:
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_active_modes() == []


class TestReadFrictionAndModes:
    def test_reads_both_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        level, modes = SessionYamlDocument(toplevel=toplevel).read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_falls_back_when_both_missing(self, tmp_path: Path) -> None:
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.default()
        assert modes == []

    def test_modes_empty_when_not_a_list(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path, content="friction_level: guided\nactive_modes: 3\n"
        )
        level, modes = SessionYamlDocument(toplevel=toplevel).read_friction_and_modes()
        assert level is FrictionLevel.GUIDED
        assert modes == []


class TestReadGatePolicyInputs:
    def test_reads_preset_and_overlays_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="gate_preset: guided\ngate_overlays: [afk]\n",
        )
        inputs = SessionYamlDocument(toplevel=toplevel).read_gate_policy_inputs()
        assert inputs["gate_preset"] == "guided"
        assert inputs["gate_overlays"] == ["afk"]

    def test_falls_back_to_pre_split_session(self, tmp_path: Path) -> None:
        toplevel = _write(
            tmp_path=tmp_path,
            content="gate_preset: adaptive\ngate_overlays: [afk]\n",
        )
        inputs = SessionYamlDocument(toplevel=toplevel).read_gate_policy_inputs()
        assert inputs["gate_preset"] == "adaptive"
        assert inputs["gate_overlays"] == ["afk"]

    def test_soft_fallbacks_when_absent(self, tmp_path: Path) -> None:
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs == {
            "friction_level": FrictionLevel.default().value,
            "active_modes": [],
            "walk_away": False,
            "gate_overrides": {},
            "gate_preset": None,
            "gate_overlays": [],
        }


class TestConfigRender:
    """GH-774: ConfigYamlDocument owns the durable-prefs template."""

    def test_defaults_to_guided_empty_modes(self) -> None:
        body = ConfigYamlDocument.render()
        assert "friction_level: guided  # strict | guided | adaptive" in body
        assert "active_modes: []" in body

    def test_renders_chosen_level_and_modes(self) -> None:
        body = ConfigYamlDocument.render(
            friction_level="adaptive", active_modes=["solo-maintainer"]
        )
        assert "friction_level: adaptive" in body
        assert "active_modes: ['solo-maintainer']" in body

    def test_round_trips_through_reader(self, tmp_path: Path) -> None:
        config = ConfigYamlDocument(toplevel=str(tmp_path))
        (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
        config.path.write_text(ConfigYamlDocument.render(friction_level="strict"))
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_friction_level() is (
            FrictionLevel.STRICT
        )


class TestConfigWrite:
    def test_creates_parents_and_writes(self, tmp_path: Path) -> None:
        ConfigYamlDocument(toplevel=str(tmp_path)).write(
            friction_level="adaptive", active_modes=["solo-maintainer"]
        )
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_write_defaults(self, tmp_path: Path) -> None:
        ConfigYamlDocument(toplevel=str(tmp_path)).write()
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.GUIDED
        assert modes == []


class TestEphemeralWrite:
    """GH-774: session.yaml is seeded ephemeral — no durable keys."""

    def test_stub_has_no_durable_keys(self) -> None:
        body = SessionYamlDocument.render_ephemeral()
        assert "friction_level" not in body
        assert "active_modes" not in body

    def test_write_creates_parents(self, tmp_path: Path) -> None:
        doc = SessionYamlDocument(toplevel=str(tmp_path))
        doc.write_ephemeral()
        assert doc.path.exists()
        # An ephemeral stub does not define durable prefs — reads default.
        assert doc.read_friction_level() is FrictionLevel.default()


class TestReadSessionIdentity:
    """ADR-0016 #753: recorded identity feeds the session_stale predicate.

    Identity is EPHEMERAL — read from session.yaml only, never config.yaml.
    """

    def test_reads_branch_and_tickets(self, tmp_path: Path) -> None:
        toplevel = _write(
            tmp_path=tmp_path,
            content="branch: user/GH-1/x\ntickets: [GH-1, GH-2]\n",
        )
        identity = SessionYamlDocument(toplevel=toplevel).read_session_identity()
        assert identity == {"branch": "user/GH-1/x", "tickets": ["GH-1", "GH-2"]}

    def test_ignores_config_yaml(self, tmp_path: Path) -> None:
        _write_config(tmp_path=tmp_path, content="branch: leaked/from/config\n")
        identity = SessionYamlDocument(toplevel=str(tmp_path)).read_session_identity()
        assert identity == {"branch": None, "tickets": []}

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
