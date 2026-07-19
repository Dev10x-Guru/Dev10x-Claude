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

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import (
    ConfigYamlDocument,
    FrictionYamlDocument,
    SessionYamlDocument,
    legacy_durable_prefs,
)
from dev10x.domain.friction_level import FrictionLevel


def _write_friction(*, content: str) -> None:
    """Write the global (isolated-tmp) friction.yaml (ADR-0018 durable home)."""
    path = Dev10xConfigDir.friction_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


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
            "allowed_overlays": None,
        }

    def test_reads_allowed_overlays_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="allowed_overlays: [afk]\n")
        inputs = SessionYamlDocument(toplevel=toplevel).read_gate_policy_inputs()
        assert inputs["allowed_overlays"] == ["afk"]

    def test_allowed_overlays_empty_list_is_declared_not_unset(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="allowed_overlays: []\n")
        inputs = SessionYamlDocument(toplevel=toplevel).read_gate_policy_inputs()
        assert inputs["allowed_overlays"] == []


class TestReadAllowedOverlays:
    """GH-805: the local repo-character overlay allow-list."""

    def test_reads_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path, content="allowed_overlays: [solo-maintainer]\n"
        )
        assert SessionYamlDocument(toplevel=toplevel).read_allowed_overlays() == [
            "solo-maintainer"
        ]

    def test_empty_list_is_declared(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="allowed_overlays: []\n")
        assert SessionYamlDocument(toplevel=toplevel).read_allowed_overlays() == []

    def test_none_when_unset(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: guided\n")
        assert SessionYamlDocument(toplevel=toplevel).read_allowed_overlays() is None

    def test_none_when_not_a_list(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="allowed_overlays: solo-maintainer\n")
        assert SessionYamlDocument(toplevel=toplevel).read_allowed_overlays() is None

    def test_none_when_both_missing(self, tmp_path: Path) -> None:
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_allowed_overlays() is None

    def test_falls_back_to_pre_split_session(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="allowed_overlays: []\n")
        assert SessionYamlDocument(toplevel=toplevel).read_allowed_overlays() == []

    def test_coerces_non_string_entries(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="allowed_overlays: [afk, 3]\n")
        assert SessionYamlDocument(toplevel=toplevel).read_allowed_overlays() == ["afk", "3"]


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

    def test_omits_allowed_overlays_when_unset(self) -> None:
        # Back-compat: the canonical body is unchanged when the repo has not
        # opted into the GH-805 guard.
        assert "allowed_overlays" not in ConfigYamlDocument.render()

    def test_emits_allowed_overlays_when_declared(self) -> None:
        body = ConfigYamlDocument.render(allowed_overlays=[])
        assert "allowed_overlays: []" in body

    def test_allowed_overlays_round_trips_through_reader(self, tmp_path: Path) -> None:
        config = ConfigYamlDocument(toplevel=str(tmp_path))
        (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
        config.path.write_text(ConfigYamlDocument.render(allowed_overlays=["afk"]))
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_allowed_overlays() == ["afk"]


class TestConfigReadFrictionAndModes:
    """GH-826: the dead ConfigYamlDocument.write path was retired; the
    combined reader stays covered by seeding config.yaml via render()."""

    def test_reads_rendered_level_and_modes(self, tmp_path: Path) -> None:
        config = ConfigYamlDocument(toplevel=str(tmp_path))
        (tmp_path / ".claude" / "Dev10x").mkdir(parents=True)
        config.path.write_text(
            ConfigYamlDocument.render(friction_level="adaptive", active_modes=["solo-maintainer"])
        )
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_defaults_when_config_absent(self, tmp_path: Path) -> None:
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.STRICT
        assert modes == []


class TestFrictionYaml:
    """ADR-0018: durable prefs live in the global friction.yaml, keyed by
    project dir-path globs. A matching entry wins over the legacy per-repo
    config.yaml; defaults apply only when neither a match nor legacy exists.
    """

    def test_matched_full_path_wins_over_legacy_config(self, tmp_path: Path) -> None:
        _write_config(tmp_path=tmp_path, content="friction_level: strict\n")
        _write_friction(
            content=(
                "defaults:\n  friction_level: guided\n"
                f"projects:\n  - match: ['{tmp_path}']\n    friction_level: adaptive\n"
            )
        )
        assert (
            SessionYamlDocument(toplevel=str(tmp_path)).read_friction_level()
            is FrictionLevel.ADAPTIVE
        )

    def test_basename_glob_matches(self, tmp_path: Path) -> None:
        _write_friction(
            content=(f"projects:\n  - match: ['{tmp_path.name}']\n    friction_level: adaptive\n")
        )
        assert (
            SessionYamlDocument(toplevel=str(tmp_path)).read_friction_level()
            is FrictionLevel.ADAPTIVE
        )

    def test_defaults_merge_under_matched_entry(self, tmp_path: Path) -> None:
        _write_friction(
            content=(
                "defaults:\n  active_modes: [solo-maintainer]\n"
                f"projects:\n  - match: ['{tmp_path.name}']\n    friction_level: adaptive\n"
            )
        )
        level, modes = SessionYamlDocument(toplevel=str(tmp_path)).read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_legacy_config_used_when_no_match(self, tmp_path: Path) -> None:
        _write_config(tmp_path=tmp_path, content="friction_level: strict\n")
        _write_friction(
            content=(
                "defaults:\n  friction_level: adaptive\n"
                "projects:\n  - match: ['zzz-no-match']\n    friction_level: guided\n"
            )
        )
        # No entry matches tmp_path -> legacy config.yaml wins over friction
        # defaults (ADR-0018 D4 one-cycle migration fallback).
        assert (
            SessionYamlDocument(toplevel=str(tmp_path)).read_friction_level()
            is FrictionLevel.STRICT
        )

    def test_defaults_used_when_no_match_and_no_legacy(self, tmp_path: Path) -> None:
        _write_friction(content="defaults:\n  friction_level: adaptive\n")
        assert (
            SessionYamlDocument(toplevel=str(tmp_path)).read_friction_level()
            is FrictionLevel.ADAPTIVE
        )

    def test_gate_inputs_from_matched_entry(self, tmp_path: Path) -> None:
        _write_friction(
            content=(
                f"projects:\n  - match: ['{tmp_path.name}']\n"
                "    gate_preset: adaptive\n    gate_overlays: [afk]\n"
            )
        )
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs["gate_preset"] == "adaptive"
        assert inputs["gate_overlays"] == ["afk"]

    def test_absent_friction_yaml_defaults(self, tmp_path: Path) -> None:
        assert (
            SessionYamlDocument(toplevel=str(tmp_path)).read_friction_level()
            is FrictionLevel.default()
        )


class TestFrictionStarterRender:
    def test_starter_has_defaults_block(self) -> None:
        body = FrictionYamlDocument.render_starter(friction_level="adaptive")
        assert "defaults:" in body
        assert "friction_level: adaptive" in body

    def test_starter_projects_are_commented(self) -> None:
        # A fresh file must have no active projects entry — the example is
        # commented so machines read only `defaults` until a human adds one.
        assert "# projects:" in FrictionYamlDocument.render_starter()


class TestMatchGlobsFor:
    """GH-812 R4: match globs the migration keys a projects[] entry by."""

    def test_returns_basename_glob_and_exact_path(self, tmp_path: Path) -> None:
        globs = FrictionYamlDocument.match_globs_for(str(tmp_path))
        assert globs == [f"*/{tmp_path.name}", str(tmp_path)]

    def test_generated_entry_matches_its_own_toplevel(self, tmp_path: Path) -> None:
        # The globs must resolve the very repo they were generated for.
        globs = FrictionYamlDocument.match_globs_for(str(tmp_path))
        _write_friction(
            content=(f"projects:\n  - match: {globs!r}\n    friction_level: adaptive\n")
        )
        assert (
            SessionYamlDocument(toplevel=str(tmp_path)).read_friction_level()
            is FrictionLevel.ADAPTIVE
        )


class TestWithProject:
    """GH-812 R4: idempotent projects[] upsert."""

    def test_appends_entry_to_empty_doc(self) -> None:
        doc = FrictionYamlDocument.with_project(
            {}, match=["*/repo"], prefs={"friction_level": "adaptive"}
        )
        assert doc["projects"] == [{"match": ["*/repo"], "friction_level": "adaptive"}]

    def test_replaces_entry_with_identical_match(self) -> None:
        base = {"projects": [{"match": ["*/repo"], "friction_level": "guided"}]}
        doc = FrictionYamlDocument.with_project(
            base, match=["*/repo"], prefs={"friction_level": "adaptive"}
        )
        assert doc["projects"] == [{"match": ["*/repo"], "friction_level": "adaptive"}]

    def test_preserves_other_entries_and_defaults(self) -> None:
        base = {
            "defaults": {"friction_level": "guided"},
            "projects": [{"match": ["*/other"], "friction_level": "strict"}],
        }
        doc = FrictionYamlDocument.with_project(
            base, match=["*/repo"], prefs={"friction_level": "adaptive"}
        )
        assert doc["defaults"] == {"friction_level": "guided"}
        assert {"match": ["*/other"], "friction_level": "strict"} in doc["projects"]
        assert {"match": ["*/repo"], "friction_level": "adaptive"} in doc["projects"]

    def test_filters_non_durable_keys(self) -> None:
        doc = FrictionYamlDocument.with_project(
            {}, match=["*/repo"], prefs={"friction_level": "adaptive", "branch": "x"}
        )
        assert doc["projects"][0] == {"match": ["*/repo"], "friction_level": "adaptive"}

    def test_tolerates_non_list_projects(self) -> None:
        doc = FrictionYamlDocument.with_project({"projects": "oops"}, match=["*/repo"], prefs={})
        assert doc["projects"] == [{"match": ["*/repo"]}]


class TestRenderDocument:
    def test_prepends_header_and_yaml_body(self) -> None:
        text = FrictionYamlDocument.render_document(
            {"projects": [{"match": ["*/repo"], "friction_level": "adaptive"}]}
        )
        assert text.startswith("# Dev10x global durable session preferences")
        assert yaml.safe_load(text)["projects"][0]["friction_level"] == "adaptive"

    def test_handles_empty_doc(self) -> None:
        text = FrictionYamlDocument.render_document({})
        assert text.startswith("# Dev10x global durable session preferences")


class TestLegacyDurablePrefs:
    """GH-812 R4: legacy-only durable reader (excludes friction.yaml)."""

    def test_reads_config_only(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        assert legacy_durable_prefs(toplevel=toplevel) == {
            "friction_level": "adaptive",
            "active_modes": ["solo-maintainer"],
        }

    def test_config_wins_over_session(self, tmp_path: Path) -> None:
        _write(tmp_path=tmp_path, content="friction_level: guided\n")
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: strict\n")
        assert legacy_durable_prefs(toplevel=toplevel) == {"friction_level": "strict"}

    def test_filters_non_durable_keys(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path, content="friction_level: guided\nbranch: feature\n"
        )
        assert legacy_durable_prefs(toplevel=toplevel) == {"friction_level": "guided"}

    def test_empty_when_no_legacy_files(self, tmp_path: Path) -> None:
        assert legacy_durable_prefs(toplevel=str(tmp_path)) == {}

    def test_ignores_friction_yaml(self, tmp_path: Path) -> None:
        # A matching friction.yaml entry must NOT leak into the legacy reader.
        _write_friction(
            content=(f"projects:\n  - match: ['{tmp_path.name}']\n    friction_level: adaptive\n")
        )
        assert legacy_durable_prefs(toplevel=str(tmp_path)) == {}
