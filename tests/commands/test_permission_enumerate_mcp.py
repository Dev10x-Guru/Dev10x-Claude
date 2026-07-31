"""CLI tests for ``dev10x permission enumerate-mcp`` (GH-919)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands import permission as permission_cmd
from dev10x.permission.service import PermissionContext
from dev10x.skills.permission import enumerate_mcp


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_*"]}}))
    return path


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    src = tmp_path / "plugin" / "src" / "dev10x" / "mcp"
    src.mkdir(parents=True)
    (src / "git_tools.py").write_text("@server.tool()\nasync def beta() -> dict: pass\n")
    return tmp_path / "plugin"


@pytest.fixture(autouse=True)
def stub_context(
    settings_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the CLI to one settings file so no real user config is touched."""
    context = PermissionContext(
        config_path=tmp_path / "projects.yaml",
        config={},
        settings_files=[settings_file],
    )
    monkeypatch.setattr(permission_cmd, "_require_settings", lambda **_kw: context)


class TestEnumerateMcpCli:
    """``--plugin-root`` drives discovery; failures exit non-zero."""

    def test_plugin_root_option_expands_wildcards(
        self,
        settings_file: Path,
        plugin_dir: Path,
    ) -> None:
        result = CliRunner().invoke(
            permission_cmd.permission,
            ["enumerate-mcp", "--plugin-root", str(plugin_dir)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        allow = json.loads(settings_file.read_text())["permissions"]["allow"]
        assert allow == ["mcp__plugin_Dev10x_cli__beta"]

    def test_dry_run_leaves_file_untouched(
        self,
        settings_file: Path,
        plugin_dir: Path,
    ) -> None:
        before = settings_file.read_text()
        result = CliRunner().invoke(
            permission_cmd.permission,
            ["enumerate-mcp", "--dry-run", "--plugin-root", str(plugin_dir)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert settings_file.read_text() == before

    def test_unresolvable_root_exits_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(enumerate_mcp, "resolve_plugin_root", lambda **_kw: None)
        result = CliRunner().invoke(
            permission_cmd.permission,
            ["enumerate-mcp"],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        assert "Could not resolve" in result.output

    def test_root_without_tools_exits_non_zero(self, tmp_path: Path) -> None:
        empty_root = tmp_path / "empty-plugin"
        empty_root.mkdir()
        result = CliRunner().invoke(
            permission_cmd.permission,
            ["enumerate-mcp", "--plugin-root", str(empty_root)],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        assert "Could not enumerate" in result.output
