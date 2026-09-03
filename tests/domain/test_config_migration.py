"""v1 → v2 durable-config migration (GH-1166, ADR-0022).

The load-bearing property under test is one-directional: **no config may
resolve to more autonomy after migration than before**. Every ambiguous,
absent, or malformed input must land on ``supervisor_review: required``,
and only an explicit low-oversight statement may produce ``none``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from dev10x.domain.config_migration import (
    migrate_configs,
    migrate_friction_yaml,
    migrate_legacy_repo_config,
    migrate_prefs,
    resolve_supervisor_review,
)
from dev10x.domain.dev10x_paths import Dev10xConfigDir


@pytest.fixture
def friction_path() -> Path:
    """The isolated global ``friction.yaml`` (see ``_isolate_dev10x_config_home``)."""
    return Dev10xConfigDir.friction_yaml()


@pytest.fixture
def write_friction(friction_path: Path):
    """Write a ``friction.yaml`` body into the isolated config home."""

    def _write(body: str) -> Path:
        friction_path.parent.mkdir(parents=True, exist_ok=True)
        friction_path.write_text(body)
        return friction_path

    return _write


@pytest.fixture
def write_legacy_config(tmp_path: Path):
    """Write a legacy per-repo ``.claude/Dev10x/config.yaml`` under a repo root."""

    def _write(body: str, *, name: str = "acme-repo") -> str:
        root = tmp_path / name
        target = root / ".claude" / "Dev10x" / "config.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        return str(root)

    return _write


def _entry(doc: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return doc["projects"][index]


class TestMappingTable:
    """One test per row of the GH-1166 v1 → v2 mapping table."""

    @pytest.mark.parametrize(
        ("prefs", "expected"),
        [
            ({"gate_preset": "adaptive", "human_review": False}, "none"),
            ({"gate_preset": "adaptive", "human_review": True}, "required"),
            ({"gate_preset": "adaptive"}, "required"),
            ({"gate_preset": "guided", "human_review": False}, "required"),
            ({"gate_preset": "guided", "human_review": True}, "required"),
            ({"gate_preset": "guided"}, "required"),
            ({"gate_preset": "strict", "human_review": False}, "required"),
            ({"gate_preset": "strict", "human_review": True}, "required"),
            ({"gate_preset": "strict"}, "required"),
            ({"friction_level": "adaptive", "human_review": False}, "none"),
            ({"friction_level": "adaptive"}, "required"),
            ({"friction_level": "guided"}, "required"),
            ({"friction_level": "strict", "human_review": False}, "required"),
            ({"human_review": False}, "none"),
            ({"human_review": True}, "required"),
            ({}, "required"),
        ],
    )
    def test_supervisor_review_row(self, prefs: dict[str, Any], expected: str) -> None:
        assert resolve_supervisor_review(prefs) == expected

    def test_walk_away_becomes_the_afk_overlay(self) -> None:
        migrated, record = migrate_prefs({"walk_away": True}, scope="t")

        assert migrated["gate_overlays"] == ["afk"]
        assert record.added_overlays == ["afk"]

    def test_walk_away_false_adds_no_overlay(self) -> None:
        migrated, _ = migrate_prefs({"walk_away": False}, scope="t")

        assert "gate_overlays" not in migrated

    def test_solo_maintainer_mode_materialises_as_an_overlay(self) -> None:
        """The read-compat seam derived this; GH-1162 removed it, so the
        migrator is now the only thing that can put the overlay there."""
        migrated, _ = migrate_prefs({"active_modes": ["solo-maintainer"]}, scope="t")

        assert migrated["gate_overlays"] == ["solo-maintainer"]
        assert migrated["active_modes"] == ["solo-maintainer"]

    def test_existing_overlays_are_not_duplicated(self) -> None:
        migrated, record = migrate_prefs({"walk_away": True, "gate_overlays": ["afk"]}, scope="t")

        assert migrated["gate_overlays"] == ["afk"]
        assert record.added_overlays == []

    def test_strict_preserves_gate_overrides_verbatim(self) -> None:
        overrides = {"merge": "ask", "request_review": "ask"}
        migrated, _ = migrate_prefs(
            {"gate_preset": "strict", "gate_overrides": overrides}, scope="t"
        )

        assert migrated["gate_overrides"] == overrides
        assert migrated["supervisor_review"] == "required"

    @pytest.mark.parametrize("preset", ["strict", "guided", "adaptive"])
    def test_retired_preset_names_are_dropped(self, preset: str) -> None:
        migrated, record = migrate_prefs({"gate_preset": preset}, scope="t")

        assert "gate_preset" not in migrated
        assert record.dropped_preset == preset

    def test_user_defined_preset_survives(self) -> None:
        """A name outside the shipped set is a real selection (ADR-0022 D-1)."""
        migrated, record = migrate_prefs({"gate_preset": "my-house-style"}, scope="t")

        assert migrated["gate_preset"] == "my-house-style"
        assert record.dropped_preset is None

    def test_v1_keys_are_removed(self) -> None:
        migrated, record = migrate_prefs(
            {"friction_level": "strict", "walk_away": True, "human_review": True},
            scope="t",
        )

        assert set(migrated) == {"supervisor_review", "gate_overlays"}
        assert sorted(record.dropped_keys) == ["friction_level", "human_review", "walk_away"]

    def test_unrelated_durable_keys_are_untouched(self) -> None:
        migrated, _ = migrate_prefs(
            {"gate_preset": "strict", "tracker": "linear", "protected_branches": ["trunk"]},
            scope="t",
        )

        assert migrated["tracker"] == "linear"
        assert migrated["protected_branches"] == ["trunk"]


class TestNoAutonomyEscalation:
    """The acceptance bar: migration never grants autonomy it did not have."""

    @pytest.mark.parametrize(
        "prefs",
        [
            {},
            {"human_review": None},
            {"human_review": "false"},
            {"human_review": "no"},
            {"human_review": 0},
            {"human_review": []},
            {"supervisor_review": "None"},
            {"supervisor_review": "no"},
            {"supervisor_review": False},
            {"supervisor_review": None},
            {"supervisor_review": ["none"]},
            {"gate_preset": "strict", "human_review": False},
            {"gate_preset": "guided", "supervisor_review": "nope"},
            {"friction_level": "strict"},
            {"friction_level": None, "walk_away": "yes"},
            {"gate_preset": 17},
        ],
    )
    def test_malformed_or_absent_input_stays_required(self, prefs: dict[str, Any]) -> None:
        """`"None"` is deliberately NOT folded — a stray Python literal (GH-1161)."""
        migrated, record = migrate_prefs(prefs, scope="t")

        assert migrated["supervisor_review"] == "required"
        assert record.supervisor_review == "required"

    @pytest.mark.parametrize(
        "prefs",
        [
            {"human_review": False},
            {"gate_preset": "adaptive", "human_review": False},
            {"supervisor_review": "none"},
            {"supervisor_review": " none "},
        ],
    )
    def test_only_an_explicit_opt_out_reaches_none(self, prefs: dict[str, Any]) -> None:
        migrated, _ = migrate_prefs(prefs, scope="t")

        assert migrated["supervisor_review"] == "none"

    def test_a_strict_repo_never_lands_on_none(self, write_friction) -> None:
        """The failure GH-1166 exists to prevent: strict → silent full auto."""
        write_friction(
            "defaults:\n"
            "  friction_level: strict\n"
            "projects:\n"
            '  - match: ["*/paranoid"]\n'
            "    friction_level: strict\n"
            "    human_review: false\n"
        )

        migrate_friction_yaml()

        doc = yaml.safe_load(Dev10xConfigDir.friction_yaml().read_text())
        assert doc["defaults"]["supervisor_review"] == "required"
        assert _entry(doc)["supervisor_review"] == "required"


class TestFrictionYamlWalk:
    def test_defaults_and_every_project_entry_are_migrated(self, write_friction) -> None:
        write_friction(
            "defaults:\n"
            "  friction_level: guided\n"
            "projects:\n"
            '  - match: ["*/solo"]\n'
            "    gate_preset: adaptive\n"
            "    human_review: false\n"
            '  - match: ["*/team"]\n'
            "    gate_preset: strict\n"
            "    walk_away: true\n"
        )

        report = migrate_friction_yaml().value

        assert report["migrated"] is True
        assert len(report["entries"]) == 3
        doc = yaml.safe_load(Dev10xConfigDir.friction_yaml().read_text())
        assert doc["defaults"]["supervisor_review"] == "required"
        assert _entry(doc, 0)["supervisor_review"] == "none"
        assert _entry(doc, 1)["supervisor_review"] == "required"
        assert _entry(doc, 1)["gate_overlays"] == ["afk"]

    def test_match_globs_survive_the_rewrite(self, write_friction) -> None:
        write_friction('projects:\n  - match: ["*/repo", "/work/repo"]\n    human_review: true\n')

        migrate_friction_yaml()

        doc = yaml.safe_load(Dev10xConfigDir.friction_yaml().read_text())
        assert _entry(doc)["match"] == ["*/repo", "/work/repo"]

    def test_canonical_header_is_re_prepended(self, write_friction) -> None:
        write_friction("defaults:\n  friction_level: strict\n")

        migrate_friction_yaml()

        assert Dev10xConfigDir.friction_yaml().read_text().startswith("# Dev10x global durable")

    def test_absent_store_is_not_an_error(self, friction_path: Path) -> None:
        report = migrate_friction_yaml().value

        assert report == {
            "path": str(friction_path),
            "migrated": False,
            "entries": [],
            "reason": "absent",
        }

    def test_unparseable_store_degrades_rather_than_crashing(self, write_friction) -> None:
        write_friction("defaults: [this is: not: a mapping\n")

        report = migrate_friction_yaml().value

        assert report["migrated"] is False
        assert report["entries"] == []

    def test_non_mapping_project_entries_are_left_alone(self, write_friction) -> None:
        write_friction(
            'projects:\n  - "a stray string"\n  - match: ["*/r"]\n    walk_away: true\n'
        )

        migrate_friction_yaml()

        doc = yaml.safe_load(Dev10xConfigDir.friction_yaml().read_text())
        assert doc["projects"][0] == "a stray string"
        assert doc["projects"][1]["gate_overlays"] == ["afk"]

    def test_dry_run_reports_without_writing(self, write_friction) -> None:
        path = write_friction("defaults:\n  friction_level: strict\n")
        before = path.read_text()

        report = migrate_friction_yaml(dry_run=True).value

        assert report["migrated"] is False
        assert report["dry_run"] is True
        assert len(report["entries"]) == 1
        assert path.read_text() == before


class TestIdempotency:
    def test_second_run_is_a_no_op(self, write_friction) -> None:
        path = write_friction(
            "defaults:\n"
            "  friction_level: strict\n"
            "projects:\n"
            '  - match: ["*/solo"]\n'
            "    gate_preset: adaptive\n"
            "    human_review: false\n"
            "    walk_away: true\n"
        )

        first = migrate_friction_yaml().value
        after_first = path.read_text()
        second = migrate_friction_yaml().value

        assert first["migrated"] is True
        assert second["migrated"] is False
        assert second["entries"] == []
        assert path.read_text() == after_first

    def test_a_v2_entry_still_carrying_a_retired_key_is_converted(self, write_friction) -> None:
        """A half-migrated entry is v1 residue, not a finished conversion."""
        write_friction(
            "defaults:\n  supervisor_review: none\n  walk_away: true\n",
        )

        report = migrate_friction_yaml().value

        assert report["migrated"] is True
        doc = yaml.safe_load(Dev10xConfigDir.friction_yaml().read_text())
        assert doc["defaults"]["supervisor_review"] == "none"
        assert doc["defaults"]["gate_overlays"] == ["afk"]
        assert "walk_away" not in doc["defaults"]

    def test_a_v2_entry_still_naming_a_retired_preset_is_converted(self, write_friction) -> None:
        write_friction("defaults:\n  supervisor_review: required\n  gate_preset: strict\n")

        report = migrate_friction_yaml().value

        assert report["migrated"] is True
        assert report["entries"][0]["dropped_preset"] == "strict"

    def test_an_already_v2_store_is_untouched(self, write_friction) -> None:
        path = write_friction(
            "defaults:\n"
            "  supervisor_review: required\n"
            "projects:\n"
            '  - match: ["*/solo"]\n'
            "    supervisor_review: none\n"
            "    gate_overlays: [solo-maintainer]\n"
        )
        before = path.read_text()

        report = migrate_friction_yaml().value

        assert report["migrated"] is False
        assert path.read_text() == before


class TestLegacyRepoConfigFold:
    def test_legacy_posture_becomes_a_repo_stem_project_entry(
        self, write_legacy_config, friction_path: Path
    ) -> None:
        root = write_legacy_config("friction_level: strict\nactive_modes: ['solo-maintainer']\n")

        report = migrate_legacy_repo_config(toplevel=root).value

        assert report["migrated"] is True
        assert report["match"] == ["*/acme-repo", "*/acme-repo-*"]
        doc = yaml.safe_load(friction_path.read_text())
        entry = _entry(doc)
        assert entry["supervisor_review"] == "required"
        assert entry["gate_overlays"] == ["solo-maintainer"]
        assert "friction_level" not in entry

    def test_the_legacy_file_itself_is_never_rewritten(self, write_legacy_config) -> None:
        """ADR-0018: Dev10x writes nothing under a repo's ``.claude/`` tree."""
        root = write_legacy_config("friction_level: guided\n")
        legacy = Path(root) / ".claude" / "Dev10x" / "config.yaml"
        before = legacy.read_text()

        migrate_legacy_repo_config(toplevel=root)

        assert legacy.read_text() == before

    def test_a_repo_already_covered_by_friction_yaml_is_skipped(
        self, write_legacy_config, write_friction
    ) -> None:
        root = write_legacy_config("human_review: false\n")
        write_friction('projects:\n  - match: ["*/acme-repo"]\n    supervisor_review: required\n')

        report = migrate_legacy_repo_config(toplevel=root).value

        assert report["migrated"] is False
        assert report["reason"] == "already-covered"

    def test_absent_legacy_file_is_not_an_error(self, tmp_path: Path) -> None:
        report = migrate_legacy_repo_config(toplevel=str(tmp_path / "nothing")).value

        assert report["migrated"] is False
        assert report["reason"] == "absent"

    def test_fold_is_idempotent(self, write_legacy_config, friction_path: Path) -> None:
        root = write_legacy_config("friction_level: strict\n")

        migrate_legacy_repo_config(toplevel=root)
        first = friction_path.read_text()
        second_report = migrate_legacy_repo_config(toplevel=root).value

        assert second_report["migrated"] is False
        assert second_report["reason"] == "already-covered"
        assert friction_path.read_text() == first


class TestMigrateConfigs:
    def test_both_stores_are_walked_and_counted(self, write_legacy_config, write_friction) -> None:
        root = write_legacy_config("friction_level: strict\n")
        write_friction("defaults:\n  friction_level: guided\n")

        report = migrate_configs(toplevel=root).value

        assert report["pending"] == 2
        assert report["friction_yaml"]["migrated"] is True
        assert report["legacy_config_yaml"]["migrated"] is True

    def test_a_clean_machine_reports_nothing_pending(self, tmp_path: Path) -> None:
        report = migrate_configs(toplevel=str(tmp_path)).value

        assert report["pending"] == 0

    def test_dry_run_leaves_both_stores_alone(self, write_legacy_config, write_friction) -> None:
        root = write_legacy_config("friction_level: strict\n")
        path = write_friction("defaults:\n  friction_level: guided\n")
        before = path.read_text()

        report = migrate_configs(toplevel=root, dry_run=True).value

        assert report["pending"] == 2
        assert report["dry_run"] is True
        assert path.read_text() == before
