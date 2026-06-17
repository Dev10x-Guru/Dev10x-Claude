"""Tests for proactive default-safe seeding (GH-603)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.skills.permission.promote import (
    apply_promotion_plan,
    build_proactive_seed_plan,
    catalog_default_safe_surface,
)

CATALOG = Path(permission_pkg.__file__).parent / "baseline-permissions.yaml"

_SYNTHETIC = {
    "groups": {
        "benign-mcp": {
            "tier": 2,
            "sensitivity": "benign",
            "rules": [
                "mcp__claude_ai_Acme__search_widgets",  # read → promotable
                "mcp__claude_ai_Acme__get_widget",  # read → promotable
                "mcp__claude_ai_Acme__create_widget",  # write → excluded
                "mcp__claude_ai_Acme__read_dm",  # sensitive → opt-in
                "WebFetch(domain:docs.acme.dev)",  # domain → promotable
                "Bash(acme ls:*)",  # not MCP/webfetch → skipped
                42,  # non-string → skipped
            ],
        },
        "opt-in-pii": {  # tier 3 → never seeded
            "tier": 3,
            "sensitivity": "pii",
            "rules": ["mcp__claude_ai_Acme__get_person"],
        },
        "untagged-tier2": {  # tier 2 but no sensitivity → not default-safe
            "tier": 2,
            "rules": ["mcp__claude_ai_Other__search_things"],
        },
    }
}


def _write_catalog(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data))
    return path


def _write_global(path: Path, allow: list[str]) -> Path:
    path.write_text(json.dumps({"permissions": {"allow": allow}}))
    return path


class TestCatalogDefaultSafeSurface:
    def test_collects_only_benign_tier2_mcp_and_domains(self, tmp_path: Path) -> None:
        catalog = _write_catalog(tmp_path / "c.yaml", _SYNTHETIC)
        tools, domains = catalog_default_safe_surface(catalog)
        assert tools == [
            "mcp__claude_ai_Acme__search_widgets",
            "mcp__claude_ai_Acme__get_widget",
            "mcp__claude_ai_Acme__create_widget",
            "mcp__claude_ai_Acme__read_dm",
        ]
        assert domains == ["docs.acme.dev"]

    def test_excludes_opt_in_and_untagged(self, tmp_path: Path) -> None:
        catalog = _write_catalog(tmp_path / "c.yaml", _SYNTHETIC)
        tools, _ = catalog_default_safe_surface(catalog)
        assert "mcp__claude_ai_Acme__get_person" not in tools  # tier-3 PII
        assert "mcp__claude_ai_Other__search_things" not in tools  # untagged

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert catalog_default_safe_surface(tmp_path / "nope.yaml") == ([], [])

    def test_invalid_yaml_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("groups: [: : :\n")
        assert catalog_default_safe_surface(bad) == ([], [])

    def test_empty_document_returns_empty(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        assert catalog_default_safe_surface(empty) == ([], [])


class TestBuildProactiveSeedPlan:
    def test_classifies_curated_surface(self, tmp_path: Path) -> None:
        catalog = _write_catalog(tmp_path / "c.yaml", _SYNTHETIC)
        global_settings = _write_global(tmp_path / "g.json", [])
        plan = build_proactive_seed_plan(
            catalog_path=catalog, global_settings_path=global_settings
        )
        assert plan.read_promotable == [
            "mcp__claude_ai_Acme__get_widget",
            "mcp__claude_ai_Acme__search_widgets",
        ]
        assert plan.writes_excluded == ["mcp__claude_ai_Acme__create_widget"]
        assert plan.sensitive_opt_in == ["mcp__claude_ai_Acme__read_dm"]
        assert plan.domains_promotable == ["docs.acme.dev"]

    def test_dedups_against_global(self, tmp_path: Path) -> None:
        catalog = _write_catalog(tmp_path / "c.yaml", _SYNTHETIC)
        global_settings = _write_global(
            tmp_path / "g.json",
            ["mcp__claude_ai_Acme__get_widget", "WebFetch(domain:docs.acme.dev)"],
        )
        plan = build_proactive_seed_plan(
            catalog_path=catalog, global_settings_path=global_settings
        )
        assert plan.read_promotable == ["mcp__claude_ai_Acme__search_widgets"]
        assert plan.already_global_tools == 1
        assert plan.already_global_domains == 1
        assert plan.domains_promotable == []

    def test_dedups_tool_listed_in_two_groups(self, tmp_path: Path) -> None:
        # Same tool curated in two benign groups → seeded once.
        dup = {
            "groups": {
                "benign-a": {
                    "tier": 2,
                    "sensitivity": "benign",
                    "rules": ["mcp__claude_ai_Acme__search_widgets"],
                },
                "benign-b": {
                    "tier": 2,
                    "sensitivity": "benign",
                    "rules": ["mcp__claude_ai_Acme__search_widgets"],
                },
            }
        }
        catalog = _write_catalog(tmp_path / "c.yaml", dup)
        global_settings = _write_global(tmp_path / "g.json", [])
        plan = build_proactive_seed_plan(
            catalog_path=catalog, global_settings_path=global_settings
        )
        assert plan.read_promotable == ["mcp__claude_ai_Acme__search_widgets"]

    def test_apply_writes_curated_reads(self, tmp_path: Path) -> None:
        catalog = _write_catalog(tmp_path / "c.yaml", _SYNTHETIC)
        global_settings = _write_global(tmp_path / "g.json", [])
        plan = build_proactive_seed_plan(
            catalog_path=catalog, global_settings_path=global_settings
        )
        result = apply_promotion_plan(plan=plan, global_settings_path=global_settings)
        written = set(json.loads(global_settings.read_text())["permissions"]["allow"])
        assert "mcp__claude_ai_Acme__search_widgets" in written
        assert "mcp__claude_ai_Acme__get_widget" in written
        # write + sensitive never auto-seeded
        assert "mcp__claude_ai_Acme__create_widget" not in written
        assert "mcp__claude_ai_Acme__read_dm" not in written
        assert result.backup_path is not None


class TestRealCatalogSeed:
    """Integration: the shipped catalog seeds reads, never PII/secret."""

    def test_seeds_sentry_and_atlassian_reads(self, tmp_path: Path) -> None:
        global_settings = _write_global(tmp_path / "g.json", [])
        plan = build_proactive_seed_plan(
            catalog_path=CATALOG, global_settings_path=global_settings
        )
        assert "mcp__claude_ai_Sentry__search_issues" in plan.read_promotable
        assert "mcp__claude_ai_Atlassian__getJiraIssue" in plan.read_promotable

    def test_never_seeds_pii_or_secret(self, tmp_path: Path) -> None:
        global_settings = _write_global(tmp_path / "g.json", [])
        plan = build_proactive_seed_plan(
            catalog_path=CATALOG, global_settings_path=global_settings
        )
        seeded = set(plan.read_promotable)
        assert "mcp__claude_ai_Google_Drive__read_file_content" not in seeded
        assert "mcp__claude_ai_Gmail__get_thread" not in seeded
