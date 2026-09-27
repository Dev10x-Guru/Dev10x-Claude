"""GH-1503: the doctor names every `*`-before-`:*` rule and its fix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.registry import load_strategies
from dev10x.skills.doctor.strategies.unmatchable_star_prefix import STRATEGY, detect
from dev10x.skills.doctor.strategy import Context


def _context(tmp_path: Path, data: dict) -> Context:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    return Context(settings_paths=(path,))


class TestDetection:
    def test_matchable_rules_are_clean(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path,
            {"permissions": {"allow": ["Bash(git log:*)"], "deny": ["Bash(mv * /dev/null*)"]}},
        )

        assert detect(context) == []

    def test_a_path_listed_twice_reports_once(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"permissions": {"deny": ["Bash(mv * /dev/null:*)"]}})

        assert len(detect(Context(settings_paths=context.settings_paths * 2))) == 1

    @pytest.mark.parametrize("body", ["{not json", "[1]"])
    def test_unreadable_files_are_skipped(self, tmp_path: Path, body: str) -> None:
        path = tmp_path / "settings.json"
        path.write_text(body)

        assert detect(Context(settings_paths=(path,))) == []


class TestFindings:
    @pytest.mark.parametrize(
        ("list_name", "rule", "severity", "operation", "replacement", "fix_word"),
        [
            (
                "deny",
                "Bash(mv * /dev/null:*)",
                "critical",
                "rewrite",
                "Bash(mv * /dev/null*)",
                "Rewrite",
            ),
            (
                "ask",
                "Bash(rm -rf /work/**:*)",
                "critical",
                "rewrite",
                "Bash(rm -rf /work/**)",
                "Rewrite",
            ),
            ("allow", "Bash(~/.claude/tools/*:*)", "drift", "drop", None, "Drop"),
        ],
    )
    def test_each_list_gets_its_own_fix(
        self,
        tmp_path: Path,
        list_name: str,
        rule: str,
        severity: str,
        operation: str,
        replacement: str | None,
        fix_word: str,
    ) -> None:
        context = _context(tmp_path, {"permissions": {list_name: [rule]}})
        finding = detect(context)[0]

        remediation = STRATEGY.remediate(finding)

        assert finding.severity == severity
        assert finding.proposed_fix.startswith(fix_word)
        assert remediation.kind == "edit_settings"
        assert remediation.target == f"permissions.{list_name}"
        assert remediation.action == {
            "path": str(context.settings_paths[0]),
            "operation": operation,
            "rule": rule,
            "replacement": replacement,
        }

    def test_a_collapsing_rewrite_is_a_prune(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path,
            {"permissions": {"ask": ["Bash(cp * ~/.claude:*)", "Bash(cp * ~/.claude*)"]}},
        )
        finding = detect(context)[0]

        assert finding.severity == "drift"
        assert finding.proposed_fix.startswith("Remove")
        assert STRATEGY.remediate(finding).action["operation"] == "prune"

    @pytest.mark.parametrize(("list_name", "word"), [("deny", "guards"), ("allow", "grants")])
    def test_evidence_says_what_stopped(self, tmp_path: Path, list_name: str, word: str) -> None:
        context = _context(tmp_path, {"permissions": {list_name: ["Bash(a*:*)"]}})

        assert f"{word} nothing" in detect(context)[0].evidence


class TestRegistration:
    def test_the_doctor_loads_it_by_default(self) -> None:
        assert "unmatchable-star-prefix" in [strategy.id for strategy in load_strategies()]
