"""Tests for `dev10x permission audit` and `permission resolve` (PAP-6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands import permission as cmd
from dev10x.commands.permission import permission
from dev10x.domain.common.result import ok
from dev10x.permission.service import PermissionContext


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestPermissionAudit:
    def test_reports_findings_from_settings(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(:*)"]}}))
        ctx = PermissionContext(
            config_path=Path("/cfg.yaml"), config={}, settings_files=[str(settings)]
        )
        monkeypatch.setattr(cmd, "load_permission_context", lambda *, include_user=None: ok(ctx))

        result = runner.invoke(permission, ["audit"])
        assert result.exit_code == 0
        assert "auditor:OVERLY_BROAD" in result.output

    def test_clean_settings_report_no_findings(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(rg:*)"]}}))
        ctx = PermissionContext(
            config_path=Path("/cfg.yaml"), config={}, settings_files=[str(settings)]
        )
        monkeypatch.setattr(cmd, "load_permission_context", lambda *, include_user=None: ok(ctx))

        result = runner.invoke(permission, ["audit"])
        assert result.exit_code == 0
        assert "No auditor findings" in result.output

    def test_no_settings_files_short_circuits(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = PermissionContext(config_path=Path("/cfg.yaml"), config={}, settings_files=[])
        monkeypatch.setattr(cmd, "load_permission_context", lambda *, include_user=None: ok(ctx))

        result = runner.invoke(permission, ["audit"])
        assert result.exit_code == 0
        assert "No settings files found." in result.output


class TestPermissionResolve:
    def test_resolves_signature_against_user_layer(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        layer = tmp_path / "projects.yaml"
        layer.write_text("base_permissions:\n  - Bash(git status:*)\n")
        monkeypatch.setattr(
            "dev10x.domain.dev10x_paths.Dev10xConfigDir.projects_yaml",
            classmethod(lambda cls: layer),
        )

        result = runner.invoke(permission, ["resolve", "Bash(git status)"])
        assert result.exit_code == 0
        assert "Effect:    allow" in result.output

    def test_context_option_is_passed_through(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        layer = tmp_path / "projects.yaml"
        layer.write_text("base_permissions:\n  - Bash(git status:*)\n")
        monkeypatch.setattr(
            "dev10x.domain.dev10x_paths.Dev10xConfigDir.projects_yaml",
            classmethod(lambda cls: layer),
        )

        result = runner.invoke(
            permission, ["resolve", "Bash(git status)", "--context", "Dev10x:git"]
        )
        assert result.exit_code == 0
        assert "Context:   Dev10x:git" in result.output
