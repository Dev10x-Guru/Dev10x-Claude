"""GH-1668: tracker rules render under every MCP server name, allow and deny alike."""

from __future__ import annotations

import pytest
from dev10x.domain.common.tracker_choice import (
    TRACKER_SERVER_ALIASES,
    Tracker,
    apply_tracker_selection,
    expand_aliases,
)

LINEAR = TRACKER_SERVER_ALIASES[Tracker.LINEAR]
DELETES = ("delete_comment", "delete_customer")


@pytest.fixture()
def config() -> dict:
    return {
        "tracker_permissions": {
            "linear": [
                "mcp__claude_ai_Linear__get_issue",
                "mcp__linear-server__get_release",
                "mcp__plugin_dev10x_cli__issue_get",
            ],
            "jira": ["mcp__claude_ai_Atlassian_Rovo__getJiraIssue"],
            "github": ["mcp__plugin_dev10x_cli__issue_list"],
        },
        "tracker_denies": {
            "linear": [f"mcp__claude_ai_Linear__{tool}" for tool in DELETES],
        },
    }


class TestExpandAliases:
    @pytest.mark.parametrize("alias", LINEAR)
    def test_a_rule_renders_under_every_alias_from_any_alias(self, alias: str) -> None:
        rendered = expand_aliases(rule=f"mcp__{alias}__get_issue", aliases=LINEAR)

        assert set(rendered) == {f"mcp__{other}__get_issue" for other in LINEAR}

    @pytest.mark.parametrize(
        "rule", ["mcp__plugin_dev10x_cli__issue_get", "Bash(git log:*)", "mcp__linearity__x"]
    )
    def test_other_rules_pass_through(self, rule: str) -> None:
        assert expand_aliases(rule=rule, aliases=LINEAR) == (rule,)


class TestApplyTracker:
    @pytest.mark.parametrize("alias", LINEAR)
    @pytest.mark.parametrize("tool", DELETES)
    def test_every_delete_is_denied_under_every_alias(
        self, config: dict, alias: str, tool: str
    ) -> None:
        merged = apply_tracker_selection(config=config, tracker=Tracker.LINEAR)

        assert f"mcp__{alias}__{tool}" in merged["base_denies"]

    @pytest.mark.parametrize("alias", LINEAR)
    @pytest.mark.parametrize("tool", ["get_issue", "get_release"])
    def test_reads_are_allowed_under_every_alias(
        self, config: dict, alias: str, tool: str
    ) -> None:
        merged = apply_tracker_selection(config=config, tracker=Tracker.LINEAR)

        assert f"mcp__{alias}__{tool}" in merged["base_permissions"]

    def test_non_tracker_server_rules_are_not_multiplied(self, config: dict) -> None:
        merged = apply_tracker_selection(config=config, tracker=Tracker.LINEAR)

        assert merged["base_permissions"].count("mcp__plugin_dev10x_cli__issue_get") == 1

    def test_jira_renders_under_its_aliases(self, config: dict) -> None:
        merged = apply_tracker_selection(config=config, tracker=Tracker.JIRA)

        assert "mcp__atlassian__getJiraIssue" in merged["base_permissions"]

    def test_tracker_without_aliases_is_unchanged(self, config: dict) -> None:
        merged = apply_tracker_selection(config=config, tracker=Tracker.GITHUB)

        assert merged["base_permissions"] == ["mcp__plugin_dev10x_cli__issue_list"]

    def test_expansion_is_idempotent(self, config: dict) -> None:
        once = apply_tracker_selection(config=config, tracker=Tracker.LINEAR)

        assert apply_tracker_selection(config=once, tracker=Tracker.LINEAR) == once
