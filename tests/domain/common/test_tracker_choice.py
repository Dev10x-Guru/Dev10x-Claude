"""Tests for tracker-keyed permission selection (GH-768)."""

from __future__ import annotations

import pytest

from dev10x.domain.common.tracker_choice import (
    Tracker,
    TrackerRules,
    apply_tracker_selection,
    parse_tracker,
    prunable_rules,
    tracker_inventory,
)

CATALOG: dict = {
    "base_permissions": ["Bash(git status:*)"],
    "base_denies": ["Bash(sudo:*)"],
    "tracker_permissions": {
        "linear": ["mcp__claude_ai_Linear__get_issue", "mcp__claude_ai_Linear__save_issue"],
        "jira": ["mcp__claude_ai_Atlassian_Rovo__getJiraIssue"],
        "github": ["mcp__plugin_Dev10x_cli__issue_get"],
    },
    "tracker_denies": {"linear": ["mcp__claude_ai_Linear__delete_comment"]},
}


class TestParseTracker:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("linear", Tracker.LINEAR),
            ("JIRA", Tracker.JIRA),
            ("  github  ", Tracker.GITHUB),
        ],
    )
    def test_accepts_known_names_case_and_space_insensitively(
        self,
        value: str,
        expected: Tracker,
    ) -> None:
        assert parse_tracker(value) is expected

    @pytest.mark.parametrize("value", ["gitlab", "", "clickup", None, 7, ["linear"]])
    def test_unknown_or_non_string_is_none(self, value: object) -> None:
        assert parse_tracker(value) is None

    def test_default_is_linear(self) -> None:
        """The pre-GH-768 unconditional behaviour, so upgrades lose nothing."""
        assert Tracker.default() is Tracker.LINEAR


class TestApplyTrackerSelection:
    def test_selected_tracker_rules_are_folded_in(self) -> None:
        merged = apply_tracker_selection(config=CATALOG, tracker=Tracker.JIRA)
        assert "mcp__claude_ai_Atlassian_Rovo__getJiraIssue" in merged["base_permissions"]

    def test_other_trackers_rules_are_left_out(self) -> None:
        merged = apply_tracker_selection(config=CATALOG, tracker=Tracker.JIRA)
        allow = merged["base_permissions"]
        assert not any(rule.startswith("mcp__claude_ai_Linear__") for rule in allow)
        assert "mcp__plugin_Dev10x_cli__issue_get" not in allow

    def test_tracker_denies_are_folded_in_too(self) -> None:
        merged = apply_tracker_selection(config=CATALOG, tracker=Tracker.LINEAR)
        assert "mcp__claude_ai_Linear__delete_comment" in merged["base_denies"]

    def test_tracker_without_a_deny_block_keeps_base_denies(self) -> None:
        merged = apply_tracker_selection(config=CATALOG, tracker=Tracker.JIRA)
        assert merged["base_denies"] == ["Bash(sudo:*)"]

    def test_tracker_independent_rules_survive(self) -> None:
        merged = apply_tracker_selection(config=CATALOG, tracker=Tracker.GITHUB)
        assert "Bash(git status:*)" in merged["base_permissions"]
        assert "Bash(sudo:*)" in merged["base_denies"]

    def test_input_config_is_not_mutated(self) -> None:
        """The catalog is cached; mutating it would leak one run's tracker."""
        apply_tracker_selection(config=CATALOG, tracker=Tracker.LINEAR)
        assert CATALOG["base_permissions"] == ["Bash(git status:*)"]
        assert CATALOG["base_denies"] == ["Bash(sudo:*)"]

    def test_is_idempotent(self) -> None:
        once = apply_tracker_selection(config=CATALOG, tracker=Tracker.LINEAR)
        twice = apply_tracker_selection(config=once, tracker=Tracker.LINEAR)
        assert once == twice

    def test_catalog_without_tracker_blocks_passes_through(self) -> None:
        legacy = {"base_permissions": ["Bash(git status:*)"]}
        merged = apply_tracker_selection(config=legacy, tracker=Tracker.LINEAR)
        assert merged["base_permissions"] == ["Bash(git status:*)"]
        assert merged["base_denies"] == []

    def test_non_string_entries_are_skipped(self) -> None:
        config = {"base_permissions": [], "tracker_permissions": {"linear": ["ok", 7, None]}}
        merged = apply_tracker_selection(config=config, tracker=Tracker.LINEAR)
        assert merged["base_permissions"] == ["ok"]

    def test_non_list_tracker_block_is_ignored(self) -> None:
        config = {"base_permissions": [], "tracker_permissions": {"linear": "nope"}}
        assert (
            apply_tracker_selection(config=config, tracker=Tracker.LINEAR)["base_permissions"]
            == []
        )

    def test_non_dict_tracker_map_is_ignored(self) -> None:
        config = {"base_permissions": [], "tracker_permissions": ["nope"]}
        assert (
            apply_tracker_selection(config=config, tracker=Tracker.LINEAR)["base_permissions"]
            == []
        )


class TestTrackerInventory:
    def test_reports_every_tracker(self) -> None:
        inventory = tracker_inventory(config=CATALOG)
        assert set(inventory) == set(Tracker)
        assert inventory[Tracker.LINEAR].deny == ("mcp__claude_ai_Linear__delete_comment",)

    def test_absent_block_is_falsy(self) -> None:
        assert not tracker_inventory(config={})[Tracker.JIRA]
        assert TrackerRules() == TrackerRules(allow=(), deny=())


class TestPrunableRules:
    def test_lists_only_other_trackers_rules(self) -> None:
        prunable = prunable_rules(config=CATALOG, tracker=Tracker.JIRA)
        assert "mcp__claude_ai_Linear__get_issue" in prunable
        assert "mcp__claude_ai_Linear__delete_comment" in prunable
        assert "mcp__plugin_Dev10x_cli__issue_get" in prunable
        assert "mcp__claude_ai_Atlassian_Rovo__getJiraIssue" not in prunable

    def test_rule_shared_with_the_selected_tracker_is_never_prunable(self) -> None:
        config = {
            "tracker_permissions": {
                "linear": ["shared_tool", "linear_only"],
                "jira": ["shared_tool"],
            }
        }
        assert prunable_rules(config=config, tracker=Tracker.JIRA) == ("linear_only",)

    def test_deduplicates(self) -> None:
        config = {"tracker_permissions": {"linear": ["dup"], "github": ["dup"]}}
        assert prunable_rules(config=config, tracker=Tracker.JIRA) == ("dup",)
