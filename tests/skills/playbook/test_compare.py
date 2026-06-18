"""Tests for ``dev10x.skills.playbook.compare`` (GH-192)."""

from __future__ import annotations

import pytest

from dev10x.skills.playbook.compare import (
    MISSING,
    DiffStatus,
    PlayDiff,
    StepDiff,
    compare_playbooks,
)


@pytest.fixture
def default_doc() -> dict:
    return {
        "version": "0.72.0",
        "fragments": {
            "shipping": [
                {"subject": "Commit", "type": "detailed", "skills": ["dev10x:git-commit"]},
                {"subject": "Create PR", "type": "detailed", "skills": ["dev10x:gh-pr-create"]},
            ]
        },
        "defaults": {
            "feature": {
                "prompt": "Use when adding new functionality.",
                "steps": [
                    {"subject": "Set up workspace", "type": "detailed"},
                    {"subject": "Implement", "type": "epic", "prompt": "Do the work."},
                    {"fragment": "shipping"},
                ],
            },
            "bugfix": {
                "steps": [
                    {"subject": "Reproduce", "type": "detailed"},
                    {"subject": "Fix", "type": "epic"},
                ]
            },
        },
    }


def _diff(default_doc: dict, user_doc: dict):
    return compare_playbooks(
        default_doc=default_doc,
        user_doc=user_doc,
        skill_key="work-on",
        user_path="/u/playbook.yaml",
        default_path="/p/playbook.yaml",
    )


class TestComparePlaybooks:
    def test_no_overrides_marks_all_plays_not_overridden(self, default_doc: dict) -> None:
        result = _diff(default_doc, {})
        statuses = {p.play_name: p.status for p in result.play_diffs}
        assert statuses == {"feature": "not-overridden", "bugfix": "not-overridden"}
        assert not result.has_findings

    def test_identical_override_is_unchanged(self, default_doc: dict) -> None:
        user = {
            "overrides": [
                {
                    "play": "feature",
                    "steps": [
                        {"subject": "Set up workspace", "type": "detailed"},
                        {"subject": "Implement", "type": "epic", "prompt": "Do the work."},
                        {"fragment": "shipping"},
                    ],
                }
            ]
        }
        result = _diff(default_doc, user)
        feature = next(p for p in result.play_diffs if p.play_name == "feature")
        assert feature.status == "unchanged"

    def test_upstream_added_step_marked_new(self, default_doc: dict) -> None:
        user = {
            "overrides": [
                {
                    "play": "feature",
                    "steps": [
                        {"subject": "Set up workspace", "type": "detailed"},
                        {"fragment": "shipping"},
                    ],
                }
            ]
        }
        result = _diff(default_doc, user)
        feature = next(p for p in result.play_diffs if p.play_name == "feature")
        assert feature.status == "changed"
        new_steps = [s for s in feature.step_diffs if s.status == "new"]
        assert [s.subject for s in new_steps] == ["Implement"]

    def test_user_only_step_marked_removed(self, default_doc: dict) -> None:
        user = {
            "overrides": [
                {
                    "play": "feature",
                    "steps": [
                        {"subject": "Set up workspace", "type": "detailed"},
                        {"subject": "Implement", "type": "epic", "prompt": "Do the work."},
                        {"subject": "Extra user step", "type": "detailed"},
                        {"fragment": "shipping"},
                    ],
                }
            ]
        }
        result = _diff(default_doc, user)
        feature = next(p for p in result.play_diffs if p.play_name == "feature")
        removed = [s for s in feature.step_diffs if s.status == "removed"]
        assert [s.subject for s in removed] == ["Extra user step"]

    def test_user_customized_field_is_preserved(self, default_doc: dict) -> None:
        """A user-set field that differs from default is reported as customized,
        not as an upstream-changed field."""
        user = {
            "overrides": [
                {
                    "play": "feature",
                    "steps": [
                        {"subject": "Set up workspace", "type": "detailed"},
                        {
                            "subject": "Implement",
                            "type": "epic",
                            "prompt": "Custom prompt — preserved.",
                        },
                        {"fragment": "shipping"},
                    ],
                }
            ]
        }
        result = _diff(default_doc, user)
        feature = next(p for p in result.play_diffs if p.play_name == "feature")
        implement = next(s for s in feature.step_diffs if s.subject == "Implement")
        assert implement.status == "changed"
        assert "prompt" in implement.customized_fields
        assert implement.upstream_changed_fields == []

    def test_user_missing_field_present_in_default_is_upstream_change(
        self, default_doc: dict
    ) -> None:
        """When the default sets a field the user hasn't, the user would
        inherit a new value — flag it as an upstream change."""
        user = {
            "overrides": [
                {
                    "play": "feature",
                    "steps": [
                        {"subject": "Set up workspace", "type": "detailed"},
                        {"subject": "Implement", "type": "epic"},  # missing prompt
                        {"fragment": "shipping"},
                    ],
                }
            ]
        }
        result = _diff(default_doc, user)
        feature = next(p for p in result.play_diffs if p.play_name == "feature")
        implement = next(s for s in feature.step_diffs if s.subject == "Implement")
        assert implement.status == "changed"
        assert implement.customized_fields == []
        field_names = [f.field_name for f in implement.upstream_changed_fields]
        assert field_names == ["prompt"]
        assert implement.upstream_changed_fields[0].user_value is MISSING

    def test_orphan_user_play_marked_removed(self, default_doc: dict) -> None:
        user = {
            "overrides": [
                {
                    "play": "legacy-play-no-longer-in-defaults",
                    "steps": [{"subject": "X", "type": "detailed"}],
                }
            ]
        }
        result = _diff(default_doc, user)
        orphan = next(
            p for p in result.play_diffs if p.play_name == "legacy-play-no-longer-in-defaults"
        )
        assert orphan.status == "removed"

    def test_fragment_diff_detects_new_step(self, default_doc: dict) -> None:
        user = {
            "fragments": {
                "shipping": [
                    {"subject": "Commit", "type": "detailed", "skills": ["dev10x:git-commit"]},
                    # missing "Create PR" — should appear as new upstream step
                ]
            }
        }
        result = _diff(default_doc, user)
        shipping = next(f for f in result.fragment_diffs if f.play_name == "shipping")
        assert shipping.status == "changed"
        new_steps = [s for s in shipping.step_diffs if s.status == "new"]
        assert [s.subject for s in new_steps] == ["Create PR"]

    def test_fragment_not_overridden_when_user_omits_it(self, default_doc: dict) -> None:
        result = _diff(default_doc, {})
        shipping = next(f for f in result.fragment_diffs if f.play_name == "shipping")
        assert shipping.status == "not-overridden"

    def test_fragment_reference_treated_as_step(self, default_doc: dict) -> None:
        """A bare ``- fragment: shipping`` entry should match a matching
        reference in the default — not be flagged as a new step."""
        user = {
            "overrides": [
                {
                    "play": "feature",
                    "steps": [
                        {"subject": "Set up workspace", "type": "detailed"},
                        {"subject": "Implement", "type": "epic", "prompt": "Do the work."},
                        {"fragment": "shipping"},
                    ],
                }
            ]
        }
        result = _diff(default_doc, user)
        feature = next(p for p in result.play_diffs if p.play_name == "feature")
        assert feature.status == "unchanged"

    def test_has_findings_false_for_clean_diff(self, default_doc: dict) -> None:
        result = _diff(default_doc, {})
        assert result.has_findings is False

    def test_has_findings_true_when_play_changes(self, default_doc: dict) -> None:
        user = {
            "overrides": [
                {
                    "play": "feature",
                    "steps": [
                        {"subject": "Set up workspace", "type": "detailed"},
                    ],
                }
            ]
        }
        result = _diff(default_doc, user)
        assert result.has_findings is True


class TestDiffStatusBehavior:
    def test_step_symbols_cover_each_status(self) -> None:
        symbols = {
            DiffStatus.NEW: "+",
            DiffStatus.REMOVED: "-",
            DiffStatus.CHANGED: "~",
            DiffStatus.UNCHANGED: " ",
        }
        for status, expected in symbols.items():
            assert StepDiff(subject="s", status=status).symbol() == expected

    def test_not_overridden_step_symbol_falls_back(self) -> None:
        step = StepDiff(subject="s", status=DiffStatus.NOT_OVERRIDDEN)
        assert step.symbol() == "?"

    def test_is_actionable_true_for_changes(self) -> None:
        for status in (DiffStatus.NEW, DiffStatus.REMOVED, DiffStatus.CHANGED):
            assert PlayDiff(play_name="p", status=status).is_actionable() is True

    def test_is_actionable_false_for_quiet_statuses(self) -> None:
        for status in (DiffStatus.UNCHANGED, DiffStatus.NOT_OVERRIDDEN):
            assert PlayDiff(play_name="p", status=status).is_actionable() is False

    def test_status_renders_as_its_string_value(self) -> None:
        assert f"{DiffStatus.NOT_OVERRIDDEN}" == "not-overridden"
        assert DiffStatus.NEW == "new"
