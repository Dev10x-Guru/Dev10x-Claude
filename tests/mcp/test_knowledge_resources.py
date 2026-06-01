"""Tests for the Dev10x MCP knowledge resources (GH-339).

Covers:
- skill_playbook resource for an existing and missing playbook
- rules_index resource
- rule_file resource for an existing and missing rule
- reference_file resource for an existing and missing reference
- skills_index resource
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

knowledge_resources = pytest.importorskip(
    "dev10x.mcp.knowledge_resources",
    reason="mcp not installed",
)


# ── helpers ────────────────────────────────────────────────────────


def _fake_root(tmp_path: Path) -> Path:
    """Build a minimal plugin-root tree under *tmp_path*."""
    # skills/<name>/references/playbook.yaml
    playbook_dir = tmp_path / "skills" / "work-on" / "references"
    playbook_dir.mkdir(parents=True)
    (playbook_dir / "playbook.yaml").write_text("defaults:\n  single: []\n", encoding="utf-8")

    # .claude/rules/INDEX.md and a named rule
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (rules_dir / "essentials.md").write_text("# Essentials\n", encoding="utf-8")

    # references/<ref>.md
    ref_dir = tmp_path / "references"
    ref_dir.mkdir(parents=True)
    (ref_dir / "git-commits.md").write_text("# Git commits\n", encoding="utf-8")

    # SKILLS.md at root
    (tmp_path / "SKILLS.md").write_text("# Skills\n", encoding="utf-8")

    return tmp_path


# ── skill_playbook ─────────────────────────────────────────────────


class TestSkillPlaybook:
    def test_returns_yaml_for_existing_skill(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.skill_playbook(skill_name="work-on")

        assert "defaults" in result
        assert "single" in result

    def test_returns_not_found_for_missing_skill(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.skill_playbook(skill_name="nonexistent-skill")

        assert "Not found" in result
        assert "nonexistent-skill" in result

    def test_returns_not_found_when_playbook_missing_from_existing_skill(
        self,
        tmp_path: Path,
    ) -> None:
        root = _fake_root(tmp_path)
        skill_dir = root / "skills" / "no-playbook-skill" / "references"
        skill_dir.mkdir(parents=True)
        # directory exists but no playbook.yaml
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.skill_playbook(skill_name="no-playbook-skill")

        assert "Not found" in result


# ── rules_index ────────────────────────────────────────────────────


class TestRulesIndex:
    def test_returns_index_content(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.rules_index()

        assert "# Index" in result

    def test_returns_not_found_when_missing(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        (root / ".claude" / "rules" / "INDEX.md").unlink()
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.rules_index()

        assert "Not found" in result


# ── rule_file ──────────────────────────────────────────────────────


class TestRuleFile:
    def test_returns_rule_content_for_existing_rule(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.rule_file(rule_name="essentials")

        assert "# Essentials" in result

    def test_returns_not_found_for_missing_rule(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.rule_file(rule_name="nonexistent-rule")

        assert "Not found" in result
        assert "nonexistent-rule" in result


# ── reference_file ─────────────────────────────────────────────────


class TestReferenceFile:
    def test_returns_reference_content_for_existing_file(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.reference_file(ref_name="git-commits")

        assert "# Git commits" in result

    def test_returns_not_found_for_missing_reference(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.reference_file(ref_name="nonexistent-ref")

        assert "Not found" in result
        assert "nonexistent-ref" in result


# ── skills_index ───────────────────────────────────────────────────


class TestSkillsIndex:
    def test_returns_skills_md_content(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.skills_index()

        assert "# Skills" in result

    def test_returns_not_found_when_skills_md_missing(self, tmp_path: Path) -> None:
        root = _fake_root(tmp_path)
        (root / "SKILLS.md").unlink()
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.skills_index()

        assert "Not found" in result


# ── path-traversal rejection (GH-339 review) ───────────────────────


class TestRejectsPathTraversal:
    @pytest.mark.parametrize("malicious", ["../secrets", "a/b", "..\\win", ".."])
    def test_skill_playbook_rejects_traversal(self, tmp_path: Path, malicious: str) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.skill_playbook(skill_name=malicious)

        assert "Invalid name" in result

    @pytest.mark.parametrize("malicious", ["../../etc/passwd", "nested/rule", ".."])
    def test_rule_file_rejects_traversal(self, tmp_path: Path, malicious: str) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.rule_file(rule_name=malicious)

        assert "Invalid name" in result

    @pytest.mark.parametrize("malicious", ["../../../root", "a/b/c", "..\\.."])
    def test_reference_file_rejects_traversal(self, tmp_path: Path, malicious: str) -> None:
        root = _fake_root(tmp_path)
        with patch(
            "dev10x.mcp.knowledge_resources.get_plugin_root",
            return_value=root,
        ):
            result = knowledge_resources.reference_file(ref_name=malicious)

        assert "Invalid name" in result


# ── registration smoke test ────────────────────────────────────────
#
# FastMCP.list_resources() / list_resource_templates() are async, but
# the underlying _resource_manager exposes synchronous equivalents:
#   _resource_manager.list_resources()  → list of Resource objects (.uri)
#   _resource_manager.list_templates()  → list of ResourceTemplate objects (.uri_template)
# We use those to inspect registration state without needing an event loop.


class TestResourcesRegistered:
    """Verify the resources are registered with the server."""

    def test_skill_playbook_template_is_registered(self) -> None:
        from dev10x.mcp._app import server

        templates = server._resource_manager.list_templates()
        uris = [t.uri_template for t in templates]
        assert "dev10x://skills/{skill_name}/playbook" in uris

    def test_rules_index_is_registered(self) -> None:
        from dev10x.mcp._app import server

        resources = server._resource_manager.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "dev10x://rules/index" in uris

    def test_rule_file_template_is_registered(self) -> None:
        from dev10x.mcp._app import server

        templates = server._resource_manager.list_templates()
        uris = [t.uri_template for t in templates]
        assert "dev10x://rules/{rule_name}" in uris

    def test_reference_file_template_is_registered(self) -> None:
        from dev10x.mcp._app import server

        templates = server._resource_manager.list_templates()
        uris = [t.uri_template for t in templates]
        assert "dev10x://references/{ref_name}" in uris

    def test_skills_index_is_registered(self) -> None:
        from dev10x.mcp._app import server

        resources = server._resource_manager.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "dev10x://skills/index" in uris
