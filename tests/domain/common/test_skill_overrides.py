"""Tests for per-project skill-pruning plans (GH-1627)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.core.domain.common.skill_overrides import (
    OverrideChange,
    PrunePlan,
    Visibility,
    apply_prune,
    is_plugin_skill,
    load_allowlist,
    parse_allowlist,
    parse_settings,
    plan_prune,
)

OFF = Visibility.OFF


@pytest.fixture
def settings() -> dict[str, Any]:
    return {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "skillOverrides": {"legacy": "off", "deploy": "name-only"},
        "enabledPlugins": {"svelte@market": True},
    }


class TestPlanPrune:
    def test_new_and_changed_names_become_changes(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(settings=settings, proposed={"ios-setup": OFF, "deploy": OFF})

        assert plan.skill_changes == (
            OverrideChange(name="deploy", before="name-only", after="off"),
            OverrideChange(name="ios-setup", before=None, after="off"),
        )
        assert plan.has_changes is True

    def test_rerun_on_pruned_settings_is_idempotent(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(settings=settings, proposed={"legacy": OFF})

        assert plan.has_changes is False
        assert plan.unchanged == ("legacy",)

    def test_allowlisted_name_is_never_changed(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(
            settings=settings, proposed={"deploy": OFF}, allowlist=frozenset({"deploy"})
        )

        assert plan.skill_changes == ()
        assert plan.kept_by_allowlist == ("deploy",)

    def test_plugin_skill_is_refused_not_written(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(settings=settings, proposed={"impeccable:audit": OFF})

        assert plan.skill_changes == ()
        assert plan.plugin_skills_refused == ("impeccable:audit",)

    def test_plugin_disable_is_planned(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(settings=settings, proposed={}, plugin_disables=("svelte@market",))

        assert plan.plugin_disables == ("svelte@market",)

    def test_already_disabled_plugin_is_unchanged(self) -> None:
        plan = plan_prune(
            settings={"enabledPlugins": {"svelte@market": False}},
            proposed={},
            plugin_disables=("svelte@market",),
        )

        assert plan.plugin_disables == ()
        assert plan.unchanged == ("svelte@market",)

    def test_plugin_with_allowlisted_skill_is_kept(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(
            settings=settings,
            proposed={},
            plugin_disables=("svelte@market",),
            allowlist=frozenset({"svelte:svelte-code-writer"}),
        )

        assert plan.plugin_disables == ()
        assert plan.kept_by_allowlist == ("svelte@market",)

    def test_malformed_overrides_read_as_empty(self) -> None:
        plan = plan_prune(settings={"skillOverrides": ["x"]}, proposed={"x": OFF})

        assert plan.existing_overrides == {}
        assert plan.skill_changes == (OverrideChange(name="x", before=None, after="off"),)


class TestApplyPrune:
    def test_merges_without_touching_other_keys(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(
            settings=settings,
            proposed={"ios-setup": OFF},
            plugin_disables=("svelte@market",),
        )

        merged = apply_prune(settings=settings, plan=plan)

        assert merged["skillOverrides"] == {
            "deploy": "name-only",
            "ios-setup": "off",
            "legacy": "off",
        }
        assert merged["enabledPlugins"] == {"svelte@market": False}
        assert merged["permissions"] == settings["permissions"]

    def test_does_not_mutate_input(self, settings: dict[str, Any]) -> None:
        plan = plan_prune(settings=settings, proposed={"ios-setup": OFF})

        apply_prune(settings=settings, plan=plan)

        assert "ios-setup" not in settings["skillOverrides"]

    def test_creates_plugin_map_when_absent(self) -> None:
        plan = PrunePlan(plugin_disables=("svelte@market",))

        assert apply_prune(settings={}, plan=plan) == {"enabledPlugins": {"svelte@market": False}}

    def test_empty_plan_returns_equal_settings(self, settings: dict[str, Any]) -> None:
        assert apply_prune(settings=settings, plan=PrunePlan()) == settings


class TestReport:
    def test_to_dict_shape(self) -> None:
        plan = PrunePlan(skill_changes=(OverrideChange(name="a", before=None, after="off"),))

        data = plan.to_dict()

        assert data["has_changes"] is True
        assert data["skill_changes"] == [{"name": "a", "before": None, "after": "off"}]


class TestLoaders:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("keep:\n  - deploy\n", frozenset({"deploy"})),
            ("", frozenset()),
            ("keep:\n", frozenset()),
            ("- deploy\n", frozenset({"deploy"})),
        ],
    )
    def test_parse_allowlist_accepts(self, text: str, expected: frozenset[str]) -> None:
        result = parse_allowlist(text=text, source="a.yaml")

        assert isinstance(result, SuccessResult)
        assert result.value == expected

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("keep: deploy\n", "must be a list"),
            ("keep:\n  - 3\n", "must be a list"),
            ("keep: [unclosed\n", "cannot parse allowlist"),
        ],
    )
    def test_parse_allowlist_rejects(self, text: str, message: str) -> None:
        result = parse_allowlist(text=text, source="a.yaml")

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_load_allowlist_missing_default_is_empty(self, tmp_path: Path) -> None:
        result = load_allowlist(path=tmp_path / "none.yaml", required=False)

        assert isinstance(result, SuccessResult)
        assert result.value == frozenset()

    def test_load_allowlist_missing_required_is_error(self, tmp_path: Path) -> None:
        result = load_allowlist(path=tmp_path / "none.yaml", required=True)

        assert isinstance(result, ErrorResult)

    def test_load_allowlist_non_utf8_is_error(self, tmp_path: Path) -> None:
        path = tmp_path / "a.yaml"
        path.write_bytes(b"\xff\xfe")

        result = load_allowlist(path=path, required=True)

        assert isinstance(result, ErrorResult)
        assert "cannot read allowlist" in result.error

    def test_load_allowlist_reads_file(self, tmp_path: Path) -> None:
        path = tmp_path / "a.yaml"
        path.write_text("keep: [deploy]\n", encoding="utf-8")

        result = load_allowlist(path=path, required=True)

        assert isinstance(result, SuccessResult)
        assert result.value == frozenset({"deploy"})

    @pytest.mark.parametrize(
        ("text", "message"),
        [("{", "cannot read"), ("[]", "must hold a JSON object, got list")],
    )
    def test_parse_settings_rejects(self, text: str, message: str) -> None:
        result = parse_settings(text=text, source="s.json")

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_parse_settings_accepts_object(self) -> None:
        result = parse_settings(text='{"a": 1}', source="s.json")

        assert isinstance(result, SuccessResult)
        assert result.value == {"a": 1}


@pytest.mark.parametrize(("name", "expected"), [("impeccable:audit", True), ("deploy", False)])
def test_is_plugin_skill(name: str, expected: bool) -> None:
    assert is_plugin_skill(name=name) is expected
