"""Tests for the in-process audit report factory (GH-142)."""

from __future__ import annotations

import pytest

analyze = pytest.importorskip("dev10x.audit.analyze", reason="dev10x not installed")


class TestBuildAuditReport:
    def test_returns_audit_report_dataclass(self, tmp_path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text('{"permissions": {"allow": []}}')

        report = analyze.build_audit_report(
            transcript="",
            settings_path=settings,
        )

        assert isinstance(report, analyze.AuditReport)
        assert report.findings == []
        assert report.proposals == []

    def test_missing_settings_file_does_not_raise(self, tmp_path) -> None:
        report = analyze.build_audit_report(
            transcript="",
            settings_path=tmp_path / "does-not-exist.json",
        )

        assert isinstance(report, analyze.AuditReport)

    def test_render_markdown_includes_sections(self, tmp_path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text('{"permissions": {"allow": []}}')

        report = analyze.build_audit_report(
            transcript="",
            settings_path=settings,
        )
        markdown = report.render_markdown()

        assert "Permission Friction Analysis" in markdown
        assert "Unmatched Tool Calls" in markdown
        assert "Script Hygiene Audit" in markdown
        assert "Proposed Allow Rules" in markdown
        assert "Summary" in markdown

    def test_uses_provided_skills_and_tools_dirs(self, tmp_path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text('{"permissions": {"allow": []}}')
        skills_dir = tmp_path / "skills"
        tools_dir = tmp_path / "tools"
        skills_dir.mkdir()
        tools_dir.mkdir()

        report = analyze.build_audit_report(
            transcript="",
            settings_path=settings,
            skills_dir=skills_dir,
            tools_dir=tools_dir,
        )

        assert report.hygiene == []


class TestAuditReportRender:
    def test_render_markdown_includes_findings_table(self, tmp_path) -> None:
        from dev10x.audit.permissions_model import Finding

        report = analyze.AuditReport(
            findings=[
                Finding(
                    index=1,
                    turn=5,
                    time="12:34",
                    tool="Bash",
                    command_display="find /opt/data",
                    classification="MISSING_RULE",
                    fix="Add: Bash(find /opt/data:*)",
                ),
            ],
        )

        markdown = report.render_markdown()

        assert "find /opt/data" in markdown
        assert "MISSING_RULE" in markdown
