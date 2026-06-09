"""Tests for the dry-run MCP/domain promotion planner (GH-470, Increment 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission.promote import (
    PromotionPlan,
    PromotionResult,
    apply_promotion_plan,
    build_promotion_plan,
    classify_mcp_tool,
    collect_webfetch_domains,
    is_sensitivity_flagged,
    render_promotion_plan,
    render_promotion_result,
)


def _write_settings(path: Path, allow: list[str]) -> Path:
    path.write_text(json.dumps({"permissions": {"allow": allow}}))
    return path


class TestClassifyMcpTool:
    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__claude_ai_Slack__slack_read_channel",
            "mcp__claude_ai_Slack__list_channel_members",
            "mcp__claude_ai_Slack__get_reactions",
            "mcp__claude_ai_Slack__search_channels",
            "mcp__claude_ai_Sentry__whoami",
        ],
    )
    def test_read_tools(self, tool: str):
        assert classify_mcp_tool(tool) == "read"

    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__claude_ai_Slack__create_canvas",
            "mcp__claude_ai_Slack__send_message_draft",
            "mcp__claude_ai_Slack__add_reaction",
            "mcp__claude_ai_Slack__schedule_message",
            "mcp__claude_ai_Square__complete_authentication",
        ],
    )
    def test_write_tools(self, tool: str):
        assert classify_mcp_tool(tool) == "write"

    def test_write_precedence_over_read(self):
        # Contains both a read token (get) and a write token (update).
        assert classify_mcp_tool("mcp__svc__get_and_update_thing") == "write"

    def test_unknown_when_no_verb_token(self):
        assert classify_mcp_tool("mcp__svc__tool_guidance") == "unknown"

    def test_malformed_name_without_separator(self):
        assert classify_mcp_tool("noseparator") == "unknown"


class TestSensitivityFlag:
    def test_private_search_is_flagged(self):
        assert is_sensitivity_flagged("mcp__claude_ai_Slack__search_public_and_private")

    def test_plain_read_not_flagged(self):
        assert not is_sensitivity_flagged("mcp__claude_ai_Slack__search_channels")


class TestCollectWebfetchDomains:
    def test_extracts_domains(self, tmp_path: Path):
        settings = _write_settings(
            tmp_path / "s.json",
            ["WebFetch(domain:arxiv.org)", "WebFetch(domain:doi.org)", "Bash(ls:*)"],
        )
        assert collect_webfetch_domains(settings) == {"arxiv.org", "doi.org"}

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert collect_webfetch_domains(tmp_path / "absent.json") == set()

    def test_unreadable_json_returns_empty(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        assert collect_webfetch_domains(bad) == set()

    def test_non_string_rules_ignored(self, tmp_path: Path):
        path = tmp_path / "s.json"
        path.write_text(json.dumps({"permissions": {"allow": ["WebFetch(domain:x.org)", 42]}}))
        assert collect_webfetch_domains(path) == {"x.org"}


class TestPromotionPlanFlags:
    def test_has_promotable_true_for_tools(self):
        assert PromotionPlan(read_promotable=["t"]).has_promotable

    def test_has_promotable_true_for_domains(self):
        assert PromotionPlan(domains_promotable=["d"]).has_promotable

    def test_has_promotable_false_when_empty(self):
        assert not PromotionPlan().has_promotable


class TestBuildPromotionPlan:
    def test_classifies_and_dedups(self, tmp_path: Path):
        project = _write_settings(
            tmp_path / "project.json",
            [
                "mcp__claude_ai_Slack__slack_read_channel",  # read → promotable
                "mcp__claude_ai_Slack__search_public_and_private",  # sensitive
                "mcp__claude_ai_Slack__send_message",  # write
                "mcp__claude_ai_HubSpot__tool_guidance",  # unknown
                "mcp__claude_ai_Linear__get_issue",  # already global
                "mcp__plugin_Dev10x_cli__pr_get",  # plugin → skipped
                "mcp__claude_ai_Slack__*",  # wildcard → skipped
                "mcp__onlyone",  # malformed prefix → skipped
                "Bash(ls:*)",  # non-mcp → skipped
                "WebFetch(domain:arxiv.org)",  # promotable domain
                "WebFetch(domain:already.global)",  # already global domain
            ],
        )
        global_settings = _write_settings(
            tmp_path / "global.json",
            [
                "mcp__claude_ai_Linear__get_issue",
                "WebFetch(domain:already.global)",
            ],
        )

        plan = build_promotion_plan(
            project_settings_paths=[project],
            global_settings_path=global_settings,
        )

        assert plan.read_promotable == ["mcp__claude_ai_Slack__slack_read_channel"]
        assert plan.sensitive_opt_in == ["mcp__claude_ai_Slack__search_public_and_private"]
        assert plan.writes_excluded == ["mcp__claude_ai_Slack__send_message"]
        assert plan.unknown_excluded == ["mcp__claude_ai_HubSpot__tool_guidance"]
        assert plan.already_global_tools == 1
        assert plan.domains_promotable == ["arxiv.org"]
        assert plan.already_global_domains == 1

    def test_dedups_across_multiple_project_files(self, tmp_path: Path):
        tool = "mcp__claude_ai_Slack__slack_read_channel"
        a = _write_settings(tmp_path / "a.json", [tool])
        b = _write_settings(tmp_path / "b.json", [tool])
        global_settings = _write_settings(tmp_path / "g.json", [])

        plan = build_promotion_plan(
            project_settings_paths=[a, b],
            global_settings_path=global_settings,
        )
        assert plan.read_promotable == [tool]


class TestRenderPromotionPlan:
    def test_renders_sections_and_items(self):
        plan = PromotionPlan(
            read_promotable=["mcp__claude_ai_Slack__slack_read_channel"],
            domains_promotable=["arxiv.org"],
            sensitive_opt_in=["mcp__claude_ai_Slack__search_public_and_private"],
            writes_excluded=["mcp__claude_ai_Slack__send_message"],
            unknown_excluded=["mcp__svc__tool_guidance"],
            already_global_tools=2,
            already_global_domains=3,
        )
        out = render_promotion_plan(plan)
        assert "DRY RUN" in out
        assert "+ mcp__claude_ai_Slack__slack_read_channel" in out
        assert "+ arxiv.org" in out
        assert "? mcp__claude_ai_Slack__search_public_and_private" in out
        assert "- mcp__claude_ai_Slack__send_message" in out
        assert "2 tool(s), 3 domain(s)" in out

    def test_renders_none_for_empty_sections(self):
        out = render_promotion_plan(PromotionPlan())
        assert "(none)" in out
        assert "NO writes" in out


class TestClassifierCorpus:
    """Validate the read/write classifier against a real allow-list corpus (GH-480 AC)."""

    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__claude_ai_Slack__slack_read_channel",
            "mcp__claude_ai_Slack__search_channels",
            "mcp__claude_ai_Linear__get_issue",
            "mcp__claude_ai_Linear__list_projects",
            "mcp__claude_ai_Sentry__find_organizations",
            "mcp__claude_ai_Sentry__whoami",
        ],
    )
    def test_real_read_tools(self, tool: str):
        assert classify_mcp_tool(tool) == "read"

    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__claude_ai_Linear__create_issue",
            "mcp__claude_ai_Slack__send_message_draft",
            "mcp__claude_ai_Vercel__deploy_to_vercel",
            "mcp__claude_ai_Google_Calendar__update_event",
        ],
    )
    def test_real_write_tools(self, tool: str):
        assert classify_mcp_tool(tool) == "write"

    def test_get_access_grant_is_write_not_read(self):
        # GH-480 known false-positive: reads as `read` by the `get` token but
        # actually mints an access grant. Write-precedence must exclude it.
        assert classify_mcp_tool("mcp__claude_ai_Vercel__get_access_to_vercel_url") == "write"

    def test_get_access_grant_excluded_from_promotable(self, tmp_path: Path):
        grant = "mcp__claude_ai_Vercel__get_access_to_vercel_url"
        plan = build_promotion_plan(
            project_settings_paths=[_write_settings(tmp_path / "p.json", [grant])],
            global_settings_path=_write_settings(tmp_path / "g.json", []),
        )
        assert plan.read_promotable == []
        assert plan.writes_excluded == [grant]

    def test_private_search_is_read_but_sensitive(self):
        # GH-480 known false-positive: a read that must NOT be default-promoted.
        tool = "mcp__claude_ai_Slack__slack_search_public_and_private"
        assert classify_mcp_tool(tool) == "read"
        assert is_sensitivity_flagged(tool)


class TestApplyPromotionPlan:
    READ_TOOL = "mcp__claude_ai_Slack__slack_read_channel"
    SENSITIVE = "mcp__claude_ai_Slack__slack_search_public_and_private"

    def _global(self, tmp_path: Path, allow: list[str]) -> Path:
        return _write_settings(tmp_path / "global.json", allow)

    def test_writes_tools_and_domains_with_backup(self, tmp_path: Path):
        g = self._global(tmp_path, ["pre-existing-rule"])
        plan = PromotionPlan(read_promotable=[self.READ_TOOL], domains_promotable=["arxiv.org"])

        result = apply_promotion_plan(plan=plan, global_settings_path=g)

        allow = json.loads(g.read_text())["permissions"]["allow"]
        assert self.READ_TOOL in allow
        assert "WebFetch(domain:arxiv.org)" in allow
        assert "pre-existing-rule" in allow
        assert result.added_tools == [self.READ_TOOL]
        assert result.added_domains == ["WebFetch(domain:arxiv.org)"]
        assert result.added_sensitive == []
        assert result.total_added == 2
        assert result.backup_path is not None and result.backup_path.is_file()

    def test_idempotent_rerun_adds_nothing(self, tmp_path: Path):
        g = self._global(tmp_path, [self.READ_TOOL])
        plan = PromotionPlan(read_promotable=[self.READ_TOOL])

        result = apply_promotion_plan(plan=plan, global_settings_path=g)

        assert result.added_tools == []
        assert result.already_present == 1
        assert result.backup_path is None
        assert json.loads(g.read_text())["permissions"]["allow"] == [self.READ_TOOL]

    def test_dry_run_makes_no_changes(self, tmp_path: Path):
        g = self._global(tmp_path, [])
        plan = PromotionPlan(read_promotable=[self.READ_TOOL])

        result = apply_promotion_plan(plan=plan, global_settings_path=g, dry_run=True)

        assert result.added_tools == [self.READ_TOOL]
        assert result.backup_path is None
        assert json.loads(g.read_text())["permissions"]["allow"] == []

    def test_sensitive_excluded_by_default(self, tmp_path: Path):
        g = self._global(tmp_path, [])
        plan = PromotionPlan(sensitive_opt_in=[self.SENSITIVE])

        result = apply_promotion_plan(plan=plan, global_settings_path=g)

        assert result.added_sensitive == []
        assert self.SENSITIVE not in json.loads(g.read_text())["permissions"]["allow"]
        assert result.backup_path is None

    def test_sensitive_included_on_opt_in(self, tmp_path: Path):
        g = self._global(tmp_path, [])
        plan = PromotionPlan(sensitive_opt_in=[self.SENSITIVE])

        result = apply_promotion_plan(plan=plan, global_settings_path=g, include_sensitive=True)

        assert result.added_sensitive == [self.SENSITIVE]
        assert self.SENSITIVE in json.loads(g.read_text())["permissions"]["allow"]

    def test_empty_plan_is_noop(self, tmp_path: Path):
        g = self._global(tmp_path, ["x"])

        result = apply_promotion_plan(plan=PromotionPlan(), global_settings_path=g)

        assert result.total_added == 0
        assert result.backup_path is None
        assert json.loads(g.read_text())["permissions"]["allow"] == ["x"]

    def test_creates_settings_when_global_missing(self, tmp_path: Path):
        g = tmp_path / "absent.json"  # does not exist yet
        plan = PromotionPlan(read_promotable=[self.READ_TOOL])

        result = apply_promotion_plan(plan=plan, global_settings_path=g)

        assert self.READ_TOOL in json.loads(g.read_text())["permissions"]["allow"]
        assert result.backup_path is None  # create_backup returns None for a missing file

    def test_stale_plan_rule_already_live_is_skipped(self, tmp_path: Path):
        # A plan listing a rule already in global (stale plan / concurrent add):
        # the live re-check under the lock must skip it without duplicating.
        already = "mcp__claude_ai_Linear__get_issue"
        g = self._global(tmp_path, [already])
        plan = PromotionPlan(read_promotable=[already, self.READ_TOOL])

        result = apply_promotion_plan(plan=plan, global_settings_path=g)

        allow = json.loads(g.read_text())["permissions"]["allow"]
        assert allow.count(already) == 1
        assert allow.count(self.READ_TOOL) == 1
        assert result.added_tools == [self.READ_TOOL]
        assert result.already_present == 1


class TestRenderPromotionResult:
    def test_renders_added_sections_and_backup(self):
        result = PromotionResult(
            added_tools=["mcp__claude_ai_Slack__slack_read_channel"],
            added_domains=["WebFetch(domain:arxiv.org)"],
            added_sensitive=["mcp__claude_ai_Slack__slack_search_public_and_private"],
            already_present=2,
            backup_path=Path("/tmp/settings.json.bak.20260609T000000Z"),
        )
        out = render_promotion_result(result)
        assert "applied to global settings" in out
        assert "Promoted read-only tools (1)" in out
        assert "+ mcp__claude_ai_Slack__slack_read_channel" in out
        assert "+ WebFetch(domain:arxiv.org)" in out
        assert "Already present in global: 2" in out
        assert "Backup: /tmp/settings.json.bak.20260609T000000Z" in out

    def test_dry_run_header_and_verb(self):
        out = render_promotion_result(PromotionResult(added_tools=["t"]), dry_run=True)
        assert "DRY RUN — no files modified" in out
        assert "Would promote read-only tools (1)" in out

    def test_no_changes_message_when_empty(self):
        out = render_promotion_result(PromotionResult())
        assert "No changes" in out
        assert "(none)" in out
