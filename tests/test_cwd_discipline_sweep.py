"""Acceptance tests for the GH-979 CWD discipline sweep (GH-245).

Each touched module must resolve its working directory through
`subprocess_utils.effective_cwd()` when a worktree is bound (MCP path),
and fall back to the process CWD when unbound (standalone path).
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

from dev10x.subprocess_utils import use_cwd


class TestHookInputCwd:
    """domain/events/hook_input.py:27 — H6."""

    def test_from_stdin_honors_bound_cwd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dev10x.domain.events.hook_input import HookInput

        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

        with use_cwd("/bound/worktree"):
            inp = HookInput.from_stdin()

        assert inp.cwd == "/bound/worktree"

    def test_from_stdin_falls_back_to_process_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.domain.events.hook_input import HookInput

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({})))

        inp = HookInput.from_stdin()

        assert inp.cwd == os.getcwd()


class TestPermissionDiagnosticsCwd:
    """hooks/permission_diagnostics.py:202 — H6."""

    @pytest.fixture()
    def write_raw(self) -> dict:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/Dev10x/gh-issue/review.md"},
        }

    @pytest.fixture(autouse=True)
    def _relative_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dev10x.hooks.permission_diagnostics import SettingsFile

        monkeypatch.setattr(
            "dev10x.hooks.permission_diagnostics.SETTINGS_PRECEDENCE",
            [
                SettingsFile(
                    label="project local",
                    path=Path(".claude/settings.local.json"),
                    precedence=3,
                ),
            ],
        )

    def test_diagnose_uses_bound_cwd_when_cwd_omitted(self, write_raw: dict) -> None:
        from dev10x.hooks.permission_diagnostics import diagnose

        with use_cwd("/bound/worktree"):
            result = diagnose(raw=write_raw)

        assert result is not None
        assert "No matching allow rule found" in result.diagnosis

    def test_diagnose_falls_back_to_process_cwd(
        self,
        tmp_path: Path,
        write_raw: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.hooks.permission_diagnostics import diagnose

        monkeypatch.chdir(tmp_path)
        result = diagnose(raw=write_raw)

        assert result is not None
        assert "No matching allow rule found" in result.diagnosis


class TestBuildAuditReportCwd:
    """audit/analyze.py — H6 seam for the deps-less analyze_permissions uv-script."""

    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": []}}))
        return path

    def test_defaults_project_root_to_effective_cwd(
        self,
        settings_file: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.audit import analyze

        captured: dict[str, str | None] = {}

        def fake_detect(
            *, calls: object, additional_dirs: object, project_root: str | None
        ) -> list:
            captured["project_root"] = project_root
            return []

        monkeypatch.setattr(analyze, "detect_known_friction", fake_detect)

        with use_cwd("/bound/worktree"):
            analyze.build_audit_report(
                transcript="",
                settings_path=settings_file,
                skills_dir=tmp_path,
                tools_dir=tmp_path,
            )

        assert captured["project_root"] == "/bound/worktree"

    def test_explicit_project_root_wins(
        self,
        settings_file: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.audit import analyze

        captured: dict[str, str | None] = {}

        def fake_detect(
            *, calls: object, additional_dirs: object, project_root: str | None
        ) -> list:
            captured["project_root"] = project_root
            return []

        monkeypatch.setattr(analyze, "detect_known_friction", fake_detect)

        analyze.build_audit_report(
            transcript="",
            settings_path=settings_file,
            skills_dir=tmp_path,
            tools_dir=tmp_path,
            project_root="/explicit/root",
        )

        assert captured["project_root"] == "/explicit/root"
