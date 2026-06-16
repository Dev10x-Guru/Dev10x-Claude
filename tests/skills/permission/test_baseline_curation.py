"""Tests for the curated read-only safe-default catalog (GH-601).

Validates the sensitivity split (default-safe vs opt-in), the absence
of any verb-blind broad CLI entry, and — cross-checking the GH-600
classifier — that no write tool leaked into a read-only group.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.skills.permission.manifest import Access, Sensitivity
from dev10x.skills.permission.promote import classify_mcp_tool

CATALOG = Path(permission_pkg.__file__).parent / "baseline-permissions.yaml"

DEFAULT_SAFE_GROUPS = (
    "mcp-sentry-readonly",
    "mcp-atlassian-readonly",
    "vercel-cli-readonly",
    "readonly-skills",
)
OPT_IN_GROUPS = {
    "mcp-google-workspace-readonly": Sensitivity.PII,
    "secrets-listing-readonly": Sensitivity.SECRET,
}


@pytest.fixture(scope="module")
def groups() -> dict:
    return yaml.safe_load(CATALOG.read_text())["groups"]


def _mcp_rules(group: dict) -> list[str]:
    return [r for r in group["rules"] if r.startswith("mcp__")]


class TestDefaultSafeGroups:
    @pytest.mark.parametrize("name", DEFAULT_SAFE_GROUPS)
    def test_tier_2_and_benign(self, groups: dict, name: str) -> None:
        group = groups[name]
        assert group["tier"] == 2
        assert group["sensitivity"] == Sensitivity.BENIGN

    @pytest.mark.parametrize("name", ["mcp-sentry-readonly", "mcp-atlassian-readonly"])
    def test_no_write_tool_leaked(self, groups: dict, name: str) -> None:
        # Cross-check against the GH-600/GH-593 classifier: a default-safe
        # group must contain zero write tools (write-precedence).
        writes = [r for r in _mcp_rules(groups[name]) if classify_mcp_tool(r) == "write"]
        assert writes == []

    def test_sentry_excludes_known_writes(self, groups: dict) -> None:
        rules = set(groups["mcp-sentry-readonly"]["rules"])
        assert "mcp__claude_ai_Sentry__update_issue" not in rules
        assert "mcp__claude_ai_Sentry__execute_sentry_tool" not in rules

    def test_atlassian_excludes_known_writes(self, groups: dict) -> None:
        rules = set(groups["mcp-atlassian-readonly"]["rules"])
        assert "mcp__claude_ai_Atlassian__createJiraIssue" not in rules
        assert "mcp__claude_ai_Atlassian__editJiraIssue" not in rules
        assert "mcp__claude_ai_Atlassian__addCommentToJiraIssue" not in rules


class TestOptInGroups:
    @pytest.mark.parametrize("name,sensitivity", OPT_IN_GROUPS.items())
    def test_tier_3_and_sensitive(self, groups: dict, name: str, sensitivity: Sensitivity) -> None:
        group = groups[name]
        assert group["tier"] == 3
        assert group["sensitivity"] == sensitivity

    def test_google_workspace_not_default_safe(self, groups: dict) -> None:
        # Drive/Gmail/Calendar reads must NOT appear in any tier-2 group.
        tier2_rules = {
            r for g in groups.values() if g.get("tier") == 2 for r in g.get("rules", [])
        }
        google_tools = [
            r for r in groups["mcp-google-workspace-readonly"]["rules"] if r.startswith("mcp__")
        ]
        assert google_tools  # sanity: the group is non-empty
        assert not (set(google_tools) & tier2_rules)

    def test_secret_listings_are_opt_in(self, groups: dict) -> None:
        rules = set(groups["secrets-listing-readonly"]["rules"])
        assert "Bash(vercel env ls:*)" in rules
        assert "Bash(gh secret list:*)" in rules


class TestNoVerbBlindBroadEntry:
    """Acceptance: no `vercel:*` / `aws-vault exec:*`-style broad entry."""

    def test_no_bare_vercel_wildcard(self, groups: dict) -> None:
        all_rules = [r for g in groups.values() for r in g.get("rules", [])]
        forbidden = {"Bash(vercel:*)", "Bash(vercel *)", "Bash(vercel)"}
        assert not (set(all_rules) & forbidden)

    def test_every_vercel_rule_is_per_subcommand(self, groups: dict) -> None:
        # Each vercel Bash rule must name a subcommand: `Bash(vercel <sub>...`.
        for group in groups.values():
            for rule in group.get("rules", []):
                if rule.startswith("Bash(vercel"):
                    inner = rule[len("Bash(") : rule.rfind(")")]
                    head = inner.split(":", 1)[0].strip()
                    assert head != "vercel", f"verb-blind broad vercel entry: {rule}"
                    assert head.startswith("vercel ")


class TestManifestAlignment:
    """The catalog agrees with the GH-600 manifest classifier.

    A default-safe MCP tool must never classify as WRITE. READ or UNKNOWN
    are both acceptable: a verb-less name like ``atlassianUserInfo`` is a
    genuine read the token heuristic cannot label, which is precisely why
    GH-601 curates it by hand rather than relying on auto-promotion.
    """

    def test_default_safe_mcp_tools_are_never_write(self, groups: dict) -> None:
        for name in ("mcp-sentry-readonly", "mcp-atlassian-readonly"):
            for rule in _mcp_rules(groups[name]):
                assert Access(classify_mcp_tool(rule)) is not Access.WRITE

    def test_search_and_get_tools_classify_read(self, groups: dict) -> None:
        # Where the heuristic CAN see a verb, it must agree with curation.
        reads = [
            r
            for name in ("mcp-sentry-readonly", "mcp-atlassian-readonly")
            for r in _mcp_rules(groups[name])
            if any(verb in r.lower() for verb in ("search", "get", "find", "lookup"))
        ]
        assert reads
        assert all(Access(classify_mcp_tool(r)) is Access.READ for r in reads)
