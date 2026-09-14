"""GH-1261: find the MCP tools that make the Bash layer optional."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.registry import DEFAULT_STRATEGY_MODULES
from dev10x.skills.doctor.strategies.shell_equivalent_mcp_tools import STRATEGY, detect
from dev10x.skills.doctor.strategy import Context


def _settings(path: Path, *, allow: list[str]) -> Path:
    path.write_text(json.dumps({"permissions": {"allow": allow}}))
    return path


@pytest.fixture
def context(tmp_path: Path):
    def build(allow: list[str]) -> Context:
        return Context(settings_paths=[_settings(tmp_path / "settings.json", allow=allow)])

    return build


class TestDetect:
    def test_a_terminal_tool_is_flagged(self, context):
        findings = detect(context(["mcp__pycharm__execute_terminal_command"]))

        assert [f.strategy_id for f in findings] == ["shell-equivalent-mcp-tools"]

    def test_it_is_critical_not_a_suggestion(self, context):
        # One such tool voids the whole chain; a suggestion understates it.
        findings = detect(context(["mcp__pycharm__execute_terminal_command"]))

        assert findings[0].severity == "critical"

    def test_the_evidence_names_what_stops_being_enforced(self, context):
        findings = detect(context(["mcp__pycharm__execute_terminal_command"]))

        assert "DX001-DX016" in findings[0].evidence
        assert "Bash() deny" in findings[0].evidence

    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__pycharm__execute_terminal_command",
            "mcp__pycharm__execute_code_on_kernel",
            "mcp__pycharm__execute_tool",
        ],
    )
    def test_every_tier_five_tool_is_caught(self, context, tool: str):
        assert detect(context([tool]))

    def test_an_unrelated_server_is_caught_too(self, context):
        # The hazard is the capability, not the vendor — detection must
        # not be scoped to the server that motivated it.
        findings = detect(context(["mcp__someide__run_command"]))

        assert findings

    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__reports__get_evaluation_report",
            "mcp__reports__retrieval_stats",
        ],
    )
    def test_a_name_that_merely_contains_a_marker_is_not_flagged(self, context, tool: str):
        # A critical finding against a harmless read teaches the reader
        # to skim past this strategy, which costs more than a miss.
        assert detect(context([tool])) == []

    def test_read_tools_are_left_alone(self, context):
        findings = detect(context(["mcp__pycharm__read_file", "mcp__pycharm__rename_refactoring"]))

        assert findings == []

    def test_no_servers_yields_nothing(self, context):
        assert detect(context([])) == []

    def test_the_remediation_proposes_a_deny(self, context):
        finding = detect(context(["mcp__pycharm__execute_terminal_command"]))[0]
        remediation = STRATEGY.remediate(finding)

        assert remediation.kind == "edit_settings"
        assert remediation.target == "permissions.deny"


def test_the_strategy_is_registered():
    # A strategy the registry does not load is a check nobody runs.
    assert "dev10x.skills.doctor.strategies.shell_equivalent_mcp_tools" in DEFAULT_STRATEGY_MODULES
