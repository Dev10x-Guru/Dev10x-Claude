"""Tests for the forbidden-token-priming strategy (GH-272)."""

from __future__ import annotations

from pathlib import Path

import pytest

strategy_mod = pytest.importorskip(
    "dev10x.skills.doctor.strategies.forbidden_token_priming",
    reason="dev10x not installed",
)
from dev10x.skills.doctor.strategy import Context, Finding  # noqa: E402


class TestDetect:
    def test_skill_md_mentioning_forbidden_token_produces_finding(
        self,
        tmp_path: Path,
    ) -> None:
        plugin_root = tmp_path / "plugin_cache"
        skill_dir = plugin_root / "skills" / "example"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "Do NOT use DEV10X_SKIP_CMD_VALIDATION as a workaround.\n",
        )

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.strategy_id == "forbidden-token-priming"
        assert finding.severity == "drift"
        assert finding.metadata["token"] == "DEV10X_SKIP_CMD_VALIDATION"

    def test_instructions_md_mentioning_forbidden_token_produces_finding(
        self,
        tmp_path: Path,
    ) -> None:
        plugin_root = tmp_path / "plugin_cache"
        skill_dir = plugin_root / "skills" / "example"
        skill_dir.mkdir(parents=True)
        (skill_dir / "instructions.md").write_text(
            "Reach for DEV10X_SKIP_CMD_VALIDATION only when ...\n",
        )

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert len(findings) == 1
        assert "instructions.md" in findings[0].location

    def test_hook_layer_docs_are_exempt(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin_cache"
        rules_dir = plugin_root / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "SKILL.md").write_text(
            "DEV10X_SKIP_CMD_VALIDATION is documented here for skill authors.\n",
        )

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert findings == []

    def test_hooks_directory_is_exempt(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin_cache"
        hooks_dir = plugin_root / "hooks" / "scripts"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "SKILL.md").write_text(
            "If DEV10X_SKIP_CMD_VALIDATION is set, the hook short-circuits.\n",
        )

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert findings == []

    def test_skill_md_without_forbidden_token_produces_no_finding(
        self,
        tmp_path: Path,
    ) -> None:
        plugin_root = tmp_path / "plugin_cache"
        skill_dir = plugin_root / "skills" / "example"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "Use the documented mktmp mechanism for temp paths.\n",
        )

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert findings == []

    def test_empty_context_produces_no_findings(self) -> None:
        findings = strategy_mod.detect(context=Context())
        assert findings == []

    def test_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin_cache"
        skill_dir = plugin_root / "skills" / "example"
        skill_dir.mkdir(parents=True)
        binary_path = skill_dir / "SKILL.md"
        binary_path.write_bytes(b"\xff\xfe\x00\x00 DEV10X_SKIP_CMD_VALIDATION")

        context = Context(plugin_cache_root=plugin_root)
        findings = strategy_mod.detect(context=context)

        assert findings == []


class TestRemediate:
    def test_finding_maps_to_file_issue_remediation(self) -> None:
        finding = Finding(
            strategy_id="forbidden-token-priming",
            severity="drift",
            location="/tmp/plugin/skills/x/SKILL.md",
            evidence="skill doc names forbidden token 'DEV10X_SKIP_CMD_VALIDATION'",
            proposed_fix="replace with structural guidance",
            metadata={
                "token": "DEV10X_SKIP_CMD_VALIDATION",
                "suggested_replacement": "structural guidance",
            },
        )
        remediation = strategy_mod.remediate(finding)
        assert remediation.kind == "file_issue"
        assert remediation.target == finding.location
        assert remediation.action["token"] == "DEV10X_SKIP_CMD_VALIDATION"


class TestStrategyConstant:
    def test_strategy_constant_exposed(self) -> None:
        assert strategy_mod.STRATEGY.id == "forbidden-token-priming"
        assert callable(strategy_mod.STRATEGY.detect)
        assert callable(strategy_mod.STRATEGY.remediate)
