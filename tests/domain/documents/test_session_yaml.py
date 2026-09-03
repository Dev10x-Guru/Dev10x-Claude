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

import pytest
import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import (
    DURABLE_KEYS,
    ConfigYamlDocument,
    FrictionYamlDocument,
    SessionYamlDocument,
    legacy_durable_prefs,
    upsert_project_prefs,
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


class TestActiveModesDerivedFromOverlays:
    """GH-1003: one posture must not produce two answers.

    The retired read-compat seam mapped modes -> overlays but never back,
    so an entry migrated to ``gate_preset`` + ``gate_overlays`` read as
    solo-maintainer to ``resolve_gate`` and as nothing at all to every
    consumer that filters on ``active_modes``. GH-1162 removed the seam;
    this overlays -> modes fold is the only translation left, and it is
    now the sole reason a v2 entry still answers ``active_modes``.
    """

    def test_overlay_only_entry_reports_the_mode(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="gate_preset: adaptive\ngate_overlays: [solo-maintainer, afk]\n",
        )
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == ["solo-maintainer"]

    def test_afk_overlay_does_not_become_a_mode(self, tmp_path: Path) -> None:
        """`afk` is overlay-only — no mode filter consumes it."""
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="gate_preset: adaptive\ngate_overlays: [afk]\n",
        )
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == []

    def test_declared_mode_is_not_duplicated_by_its_overlay(self, tmp_path: Path) -> None:
        """The hand-written mirror entries in friction.yaml stay idempotent."""
        toplevel = _write_config(
            tmp_path=tmp_path,
            content=("active_modes: [solo-maintainer]\ngate_overlays: [solo-maintainer, afk]\n"),
        )
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == ["solo-maintainer"]

    def test_structural_modes_survive_the_fold(self, tmp_path: Path) -> None:
        """Declared modes keep their order; derived ones append."""
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="active_modes: [swarm-child]\ngate_overlays: [solo-maintainer]\n",
        )
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == [
            "swarm-child",
            "solo-maintainer",
        ]

    def test_malformed_overlays_are_ignored(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="active_modes: [swarm-child]\ngate_overlays: solo-maintainer\n",
        )
        assert SessionYamlDocument(toplevel=toplevel).read_active_modes() == ["swarm-child"]

    def test_friction_and_modes_folds_overlays_too(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="friction_level: adaptive\ngate_overlays: [solo-maintainer]\n",
        )
        level, modes = SessionYamlDocument(toplevel=toplevel).read_friction_and_modes()
        assert level is FrictionLevel.ADAPTIVE
        assert modes == ["solo-maintainer"]

    def test_gate_policy_inputs_keep_the_raw_declared_modes(self, tmp_path: Path) -> None:
        """The resolver derives overlays itself — folding here would double-count."""
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="gate_preset: adaptive\ngate_overlays: [solo-maintainer]\n",
        )
        inputs = SessionYamlDocument(toplevel=toplevel).read_gate_policy_inputs()
        assert inputs["active_modes"] == []
        assert inputs["gate_overlays"] == ["solo-maintainer"]


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
            # ``None``, not the FrictionLevel default: the gate layer must be
            # able to tell "no legacy posture declared" (resolve at the
            # ADR-0022 D-1 baseline) from "explicitly strict" (a retired name
            # that must fail loudly rather than escalate autonomy, GH-1159).
            "friction_level": None,
            "active_modes": [],
            "walk_away": False,
            "gate_overrides": {},
            "gate_preset": None,
            "gate_overlays": [],
            "allowed_overlays": None,
            # Absent reads as `required` — the supervisor reads it (ADR-0022).
            "supervisor_review": "required",
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


class TestReadSupervisorReview:
    """ADR-0022 D-2 / GH-1161: the renamed durable review posture.

    ``human_review``'s name conflated the session supervisor with the wider
    team, which is why it could only ever gate ``merge``. The enum splits
    them, keeps the boolean readable as a deprecated alias for one release,
    and preserves the unset → safe-pole direction exactly.
    """

    def test_reads_the_declared_value(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="supervisor_review: none\n")
        assert SessionYamlDocument(toplevel=toplevel).read_supervisor_review() == "none"

    def test_defaults_to_required_when_missing(self, tmp_path: Path) -> None:
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_supervisor_review() == "required"

    @pytest.mark.parametrize("raw", ['"no"', "false", "null", "[]", '"None "'])
    def test_malformed_reads_as_required(self, tmp_path: Path, raw: str) -> None:
        # Only the exact `none` literal disables the park; everything else
        # fails toward MORE oversight.
        toplevel = _write_config(tmp_path=tmp_path, content=f"supervisor_review: {raw}\n")
        assert SessionYamlDocument(toplevel=toplevel).read_supervisor_review() == "required"

    @pytest.mark.parametrize(("legacy", "expected"), [("true", "required"), ("false", "none")])
    def test_legacy_human_review_alias_is_honoured(
        self, tmp_path: Path, legacy: str, expected: str
    ) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content=f"human_review: {legacy}\n")
        assert SessionYamlDocument(toplevel=toplevel).read_supervisor_review() == expected

    def test_explicit_key_outranks_the_legacy_alias(self, tmp_path: Path) -> None:
        # A half-migrated file must not silently keep the old answer.
        toplevel = _write_config(
            tmp_path=tmp_path, content="human_review: true\nsupervisor_review: none\n"
        )
        assert SessionYamlDocument(toplevel=toplevel).read_supervisor_review() == "none"

    @pytest.mark.parametrize(("declared", "expected"), [("required", True), ("none", False)])
    def test_deprecated_boolean_reader_preserves_polarity(
        self, tmp_path: Path, declared: str, expected: bool
    ) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content=f"supervisor_review: {declared}\n")
        assert SessionYamlDocument(toplevel=toplevel).read_human_review() is expected


class TestReadHumanReview:
    """ADR-0019 / GH-950: the durable, project-wide review posture.

    Replaces the ephemeral ``review-deferred`` mode, which was written to
    the retired per-repo ``session.yaml`` and so was never read back once a
    ``friction.yaml`` entry matched the repo. Absent/malformed must resolve
    to ``True`` — a bad value fails toward MORE oversight, never less.
    """

    def test_reads_false_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="human_review: false\n")
        assert SessionYamlDocument(toplevel=toplevel).read_human_review() is False

    def test_reads_true_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="human_review: true\n")
        assert SessionYamlDocument(toplevel=toplevel).read_human_review() is True

    def test_defaults_to_true_when_unset(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: guided\n")
        assert SessionYamlDocument(toplevel=toplevel).read_human_review() is True

    def test_defaults_to_true_when_both_missing(self, tmp_path: Path) -> None:
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_human_review() is True

    def test_non_boolean_string_reads_as_true(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content='human_review: "no"\n')
        assert SessionYamlDocument(toplevel=toplevel).read_human_review() is True

    def test_explicit_null_reads_as_true(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="human_review: null\n")
        assert SessionYamlDocument(toplevel=toplevel).read_human_review() is True

    def test_falls_back_to_pre_split_session(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="human_review: false\n")
        assert SessionYamlDocument(toplevel=toplevel).read_human_review() is False

    def test_matching_friction_project_entry_wins(self, tmp_path: Path) -> None:
        """A matched projects[] entry wins outright — the GH-950 precedence."""
        _write_friction(
            content=yaml.safe_dump(
                {
                    "defaults": {"human_review": True},
                    "projects": [{"match": [str(tmp_path)], "human_review": False}],
                }
            )
        )
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_human_review() is False

    def test_friction_defaults_apply_without_project_entry(self, tmp_path: Path) -> None:
        _write_friction(content=yaml.safe_dump({"defaults": {"human_review": False}}))
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_human_review() is False

    def test_matched_entry_shadows_permissive_default(self, tmp_path: Path) -> None:
        """A project entry that omits the key inherits the defaults' value."""
        _write_friction(
            content=yaml.safe_dump(
                {
                    "defaults": {"human_review": False},
                    "projects": [{"match": [str(tmp_path)], "friction_level": "adaptive"}],
                }
            )
        )
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_human_review() is False

    def test_is_a_durable_key(self) -> None:
        """Must be in DURABLE_KEYS or readers filter it out of project entries."""
        assert "human_review" in DURABLE_KEYS


class TestReadProtectedBranches:
    """GH-1031: the durable force-push protected-branch override.

    A project whose integration branch is not one of the shell script's
    defaults had no way to protect it except passing ``protected_branches``
    on every ``push_safe`` call — which an unattended agent never does,
    exactly when an unprotected force-push costs the most. ``None`` means
    "no override", so the script's own wider default still applies.
    """

    def test_reads_a_list_from_config(self, tmp_path: Path) -> None:
        toplevel = _write_config(
            tmp_path=tmp_path,
            content="protected_branches:\n  - main\n  - release/*\n",
        )
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() == [
            "main",
            "release/*",
        ]

    def test_unset_reads_as_none(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="friction_level: guided\n")
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() is None

    def test_both_files_missing_reads_as_none(self, tmp_path: Path) -> None:
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_protected_branches() is None

    def test_explicit_empty_list_reads_as_none(self, tmp_path: Path) -> None:
        """An empty override must NOT read as 'protect nothing'."""
        toplevel = _write_config(tmp_path=tmp_path, content="protected_branches: []\n")
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() is None

    def test_non_list_reads_as_none(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="protected_branches: main\n")
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() is None

    def test_blank_and_null_entries_are_dropped(self, tmp_path: Path) -> None:
        """A stray entry must not become a --protected '' flag."""
        toplevel = _write_config(
            tmp_path=tmp_path,
            content='protected_branches:\n  - main\n  - ""\n  - null\n  - "  "\n',
        )
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() == ["main"]

    def test_all_entries_unusable_reads_as_none(self, tmp_path: Path) -> None:
        """Degrading to the script default beats protecting nothing."""
        toplevel = _write_config(tmp_path=tmp_path, content='protected_branches:\n  - ""\n')
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() is None

    def test_entries_are_stringified(self, tmp_path: Path) -> None:
        toplevel = _write_config(tmp_path=tmp_path, content="protected_branches:\n  - 2\n")
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() == ["2"]

    def test_matching_friction_project_entry_wins(self, tmp_path: Path) -> None:
        _write_friction(
            content=yaml.safe_dump(
                {
                    "defaults": {"protected_branches": ["main"]},
                    "projects": [
                        {"match": [str(tmp_path)], "protected_branches": ["trunk", "release/*"]}
                    ],
                }
            )
        )
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_protected_branches() == [
            "trunk",
            "release/*",
        ]

    def test_friction_defaults_apply_without_project_entry(self, tmp_path: Path) -> None:
        _write_friction(content=yaml.safe_dump({"defaults": {"protected_branches": ["trunk"]}}))
        assert SessionYamlDocument(toplevel=str(tmp_path)).read_protected_branches() == ["trunk"]

    def test_falls_back_to_pre_split_session(self, tmp_path: Path) -> None:
        toplevel = _write(tmp_path=tmp_path, content="protected_branches:\n  - trunk\n")
        assert SessionYamlDocument(toplevel=toplevel).read_protected_branches() == ["trunk"]

    def test_is_a_durable_key(self) -> None:
        """Must be in DURABLE_KEYS or readers filter it out of project entries."""
        assert "protected_branches" in DURABLE_KEYS


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
        body = FrictionYamlDocument.render_starter(supervisor_review="none")
        assert "defaults:" in body
        assert "supervisor_review: none" in body

    def test_starter_defaults_to_the_safe_pole(self) -> None:
        assert "supervisor_review: required" in FrictionYamlDocument.render_starter()

    def test_starter_carries_no_retired_gate_keys(self) -> None:
        # Schema v2 (ADR-0022 D-1/GH-1164): one baseline, so `gate_preset` has
        # nothing to select; `friction_level` no longer reaches the gate layer.
        body = FrictionYamlDocument.render_starter()
        assert "friction_level:" not in body
        assert "gate_preset:" not in body

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


class TestUpsertCarriesForwardDurableKeys:
    """GH-1068 F3: a narrower entry must not silently drop `human_review`.

    Resolution is first-match-wins, so a worktree-path-scoped entry written by
    `set-friction` becomes the only entry the resolver sees for that worktree.
    Written as a bare preset it dropped the repo entry's durable keys, and
    `human_review` coerces toward `True` — a repo configured `human_review:
    false` started demanding human review inside the worktree.
    """

    @staticmethod
    def _write_repo_entry(target: Path, match: list[str]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(
                {
                    "projects": [
                        {
                            "match": match,
                            "gate_preset": "guided",
                            "gate_overlays": ["afk"],
                            "human_review": False,
                            "protected_branches": ["main"],
                            "allowed_overlays": [],
                        }
                    ]
                }
            )
        )

    def test_narrower_entry_inherits_non_gate_keys_from_repo_entry(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        self._write_repo_entry(target, ["*/myrepo"])
        upsert_project_prefs(
            toplevel=str(tmp_path / "agent-abc"),
            prefs={"gate_preset": "adaptive"},
            path=target,
            match=["*/agent-abc"],
            inherit_from=[str(tmp_path / "agent-abc"), "/work/myrepo"],
        )
        written = yaml.safe_load(target.read_text())["projects"][-1]
        assert written["match"] == ["*/agent-abc"]
        assert written["human_review"] is False
        assert written["protected_branches"] == ["main"]
        assert written["allowed_overlays"] == []

    def test_gate_axis_keys_are_replaced_not_inherited(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        self._write_repo_entry(target, ["*/myrepo"])
        upsert_project_prefs(
            toplevel=str(tmp_path / "agent-abc"),
            prefs={"gate_preset": "adaptive"},
            path=target,
            match=["*/agent-abc"],
            inherit_from=[str(tmp_path / "agent-abc"), "/work/myrepo"],
        )
        written = yaml.safe_load(target.read_text())["projects"][-1]
        assert written["gate_preset"] == "adaptive"
        assert "gate_overlays" not in written

    def test_explicit_prefs_win_over_inherited(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        self._write_repo_entry(target, ["*/myrepo"])
        upsert_project_prefs(
            toplevel="/work/myrepo",
            prefs={"gate_preset": "strict", "human_review": True},
            path=target,
            match=["*/myrepo"],
        )
        written = yaml.safe_load(target.read_text())["projects"][0]
        assert written["human_review"] is True

    def test_more_specific_probe_wins_over_repo_entry(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        target.write_text(
            yaml.safe_dump(
                {
                    "projects": [
                        {"match": ["*/agent-abc"], "human_review": True},
                        {"match": ["*/myrepo"], "human_review": False},
                    ]
                }
            )
        )
        upsert_project_prefs(
            toplevel=str(tmp_path / "agent-abc"),
            prefs={"gate_preset": "adaptive"},
            path=target,
            match=["*/agent-abc"],
            inherit_from=[str(tmp_path / "agent-abc"), "/work/myrepo"],
        )
        entries = yaml.safe_load(target.read_text())["projects"]
        assert entries[0]["human_review"] is True

    def test_no_matching_entry_writes_a_bare_preset(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        upsert_project_prefs(
            toplevel=str(tmp_path / "fresh"),
            prefs={"gate_preset": "adaptive"},
            path=target,
        )
        assert yaml.safe_load(target.read_text())["projects"][0] == {
            "match": FrictionYamlDocument.match_globs_for(str(tmp_path / "fresh")),
            "gate_preset": "adaptive",
        }


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
