"""Tests for MCP glob enumeration in upgrade-cleanup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import enumerate_mcp


class TestDiscoverMcpTools:
    """Parses @server.tool() decorators from MCP server files."""

    @pytest.fixture
    def fake_root(self, tmp_path: Path) -> Path:
        # After GH-243/A6 the cli server handlers live in per-domain
        # *_tools.py modules; server_cli.py is now a thin composer.
        src = tmp_path / "src" / "dev10x" / "mcp"
        src.mkdir(parents=True)
        (src / "github_tools.py").write_text(
            "from dev10x.mcp._app import server\n"
            "\n"
            "@server.tool()\n"
            "async def alpha() -> dict: pass\n"
            "\n"
            "def _private(): pass\n"
        )
        (src / "git_tools.py").write_text(
            "from dev10x.mcp._app import server\n"
            "\n"
            "@server.tool()\n"
            "async def beta() -> dict: pass\n"
        )
        (src / "plan_tools.py").write_text("# empty\n")
        (src / "audit_tools.py").write_text("# empty\n")
        (src / "misc_tools.py").write_text("# empty\n")
        (src / "server_db.py").write_text(
            "from mcp.server.fastmcp import FastMCP\n"
            "server = FastMCP(name='y')\n"
            "\n"
            "@server.tool()\n"
            "async def query() -> dict: pass\n"
        )
        return tmp_path

    def test_discovers_both_servers(self, fake_root: Path) -> None:
        result = enumerate_mcp.discover_mcp_tools(root=fake_root)
        assert "Dev10x_cli" in result
        assert "Dev10x_db" in result

    def test_cli_tools_are_fully_qualified(self, fake_root: Path) -> None:
        result = enumerate_mcp.discover_mcp_tools(root=fake_root)
        assert "mcp__plugin_Dev10x_cli__alpha" in result["Dev10x_cli"]
        assert "mcp__plugin_Dev10x_cli__beta" in result["Dev10x_cli"]

    def test_db_tools_are_fully_qualified(self, fake_root: Path) -> None:
        result = enumerate_mcp.discover_mcp_tools(root=fake_root)
        assert result["Dev10x_db"] == ["mcp__plugin_Dev10x_db__query"]

    def test_skips_undecorated_functions(self, fake_root: Path) -> None:
        result = enumerate_mcp.discover_mcp_tools(root=fake_root)
        assert all("_private" not in t for t in result["Dev10x_cli"])

    def test_missing_server_file_yields_empty_catalog(self, tmp_path: Path) -> None:
        result = enumerate_mcp.discover_mcp_tools(root=tmp_path)
        assert result == {}


class TestExpandRules:
    """Replaces MCP wildcards with enumerated tools, deduplicates."""

    @pytest.fixture
    def catalog(self) -> dict[str, list[str]]:
        return {
            "Dev10x_cli": [
                "mcp__plugin_Dev10x_cli__alpha",
                "mcp__plugin_Dev10x_cli__beta",
            ],
            "Dev10x_db": ["mcp__plugin_Dev10x_db__query"],
        }

    def test_expands_wildcard(self, catalog: dict[str, list[str]]) -> None:
        new, removed, added = enumerate_mcp.expand_rules(["mcp__plugin_Dev10x_*"], catalog)
        assert removed == ["mcp__plugin_Dev10x_*"]
        assert "mcp__plugin_Dev10x_cli__alpha" in new
        assert "mcp__plugin_Dev10x_cli__beta" in new
        assert "mcp__plugin_Dev10x_db__query" in new
        assert len(added) == 3

    def test_preserves_non_mcp_rules(self, catalog: dict[str, list[str]]) -> None:
        new, _, _ = enumerate_mcp.expand_rules(
            ["Bash(git status:*)", "mcp__plugin_Dev10x_*"], catalog
        )
        assert "Bash(git status:*)" in new

    def test_deduplicates_already_present(self, catalog: dict[str, list[str]]) -> None:
        new, _, added = enumerate_mcp.expand_rules(
            [
                "mcp__plugin_Dev10x_cli__alpha",
                "mcp__plugin_Dev10x_*",
            ],
            catalog,
        )
        assert new.count("mcp__plugin_Dev10x_cli__alpha") == 1
        assert "mcp__plugin_Dev10x_cli__alpha" not in added

    def test_no_wildcards_returns_allow_unchanged(self, catalog: dict[str, list[str]]) -> None:
        allow = ["Bash(ls:*)", "mcp__plugin_Dev10x_cli__alpha"]
        new, removed, added = enumerate_mcp.expand_rules(allow, catalog)
        assert new == allow
        assert removed == []
        assert added == []


class TestExpandSettingsFile:
    """End-to-end on a settings.local.json."""

    @pytest.fixture
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(git status:*)",
                            "mcp__plugin_Dev10x_*",
                        ]
                    }
                },
                indent=2,
            )
        )
        return path

    @pytest.fixture
    def catalog(self) -> dict[str, list[str]]:
        return {"Dev10x_cli": ["mcp__plugin_Dev10x_cli__foo"]}

    def test_dry_run_does_not_modify_file(
        self,
        settings_file: Path,
        catalog: dict[str, list[str]],
    ) -> None:
        before = settings_file.read_text()
        enumerate_mcp.expand_settings_file(settings_file, catalog, dry_run=True)
        assert settings_file.read_text() == before

    def test_applies_expansion(
        self,
        settings_file: Path,
        catalog: dict[str, list[str]],
    ) -> None:
        count, _ = enumerate_mcp.expand_settings_file(settings_file, catalog, dry_run=False)
        assert count > 0
        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert "mcp__plugin_Dev10x_*" not in allow
        assert "mcp__plugin_Dev10x_cli__foo" in allow

    def test_unreadable_file_reports_skip(
        self,
        tmp_path: Path,
        catalog: dict[str, list[str]],
    ) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        count, messages = enumerate_mcp.expand_settings_file(path, catalog, dry_run=False)
        assert count == 0
        assert any("SKIP" in m for m in messages)

    def test_idempotent(
        self,
        settings_file: Path,
        catalog: dict[str, list[str]],
    ) -> None:
        enumerate_mcp.expand_settings_file(settings_file, catalog, dry_run=False)
        count, _ = enumerate_mcp.expand_settings_file(settings_file, catalog, dry_run=False)
        assert count == 0
