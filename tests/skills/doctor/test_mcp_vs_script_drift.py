"""Tests for the mcp-vs-script-drift strategy (GH-87)."""

from __future__ import annotations

from pathlib import Path

import pytest

strategy_mod = pytest.importorskip(
    "dev10x.skills.doctor.strategies.mcp_vs_script_drift",
    reason="dev10x not installed",
)
from dev10x.skills.doctor.strategy import Context  # noqa: E402


class TestDetect:
    def test_memory_referencing_script_token_produces_finding(self, tmp_path: Path) -> None:
        memory_root = tmp_path / "memory"
        memory_root.mkdir()
        (memory_root / "old.md").write_text(
            "Never use the /tmp/Dev10x/bin/mktmp.sh script — prefer the MCP tool.\n",
        )

        context = Context(memory_roots=(memory_root,))
        findings = strategy_mod.detect(context=context)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.strategy_id == "mcp-vs-script-drift"
        assert finding.severity == "drift"
        assert finding.data is not None
        assert finding.data.mcp_tool == "mcp__plugin_Dev10x_cli__mktmp"
        assert finding.data.kind == "edit_memory"

    def test_skill_md_with_script_before_mcp_produces_finding(
        self,
        tmp_path: Path,
    ) -> None:
        plugin_root = tmp_path / "plugin_cache"
        skill_dir = plugin_root / "skills" / "example"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "use the script: skills/gh-context/scripts/gh-pr-detect.sh\n"
            "...later: mcp__plugin_Dev10x_cli__pr_detect is the MCP form\n",
        )

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert len(findings) == 1
        assert findings[0].severity == "suggestion"

    def test_skill_md_with_mcp_only_does_not_produce_finding(
        self,
        tmp_path: Path,
    ) -> None:
        plugin_root = tmp_path / "plugin_cache"
        skill_dir = plugin_root / "skills" / "example"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "use mcp__plugin_Dev10x_cli__pr_detect for PR detection.\n",
        )

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert findings == []

    def test_empty_context_produces_no_findings(self) -> None:
        findings = strategy_mod.detect(context=Context())
        assert findings == []


class TestRemediate:
    def test_memory_finding_maps_to_edit_memory(self) -> None:
        from dev10x.skills.doctor.strategy import Finding

        finding = Finding(
            strategy_id="mcp-vs-script-drift",
            severity="drift",
            location="/tmp/memory/old.md",
            evidence="memory references obsolete script ('/tmp/.../mktmp.sh')",
            proposed_fix="rewrite memory body",
            data=strategy_mod.ScriptDriftRemediation(
                mcp_tool="mcp__plugin_Dev10x_cli__mktmp",
                kind="edit_memory",
            ),
        )

        remediation = strategy_mod.remediate(finding=finding)

        assert remediation.kind == "edit_memory"
        assert remediation.target == "/tmp/memory/old.md"
        assert remediation.action["mcp_tool"] == "mcp__plugin_Dev10x_cli__mktmp"

    def test_skill_md_finding_maps_to_file_issue(self) -> None:
        from dev10x.skills.doctor.strategy import Finding

        finding = Finding(
            strategy_id="mcp-vs-script-drift",
            severity="suggestion",
            location="/plugin/skills/example/SKILL.md",
            evidence="SKILL.md shows script form before MCP form",
            proposed_fix="reorder",
            data=strategy_mod.ScriptDriftRemediation(
                mcp_tool="mcp__plugin_Dev10x_cli__pr_detect",
                kind="file_issue",
            ),
        )

        remediation = strategy_mod.remediate(finding=finding)

        assert remediation.kind == "file_issue"


class TestModuleExport:
    def test_strategy_constant_is_exported(self) -> None:
        assert hasattr(strategy_mod, "STRATEGY")
        assert strategy_mod.STRATEGY.id == "mcp-vs-script-drift"
