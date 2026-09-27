"""GH-1501: the doctor reports rules still spelled for the ``Dev10x`` plugin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.registry import load_strategies
from dev10x.skills.doctor.strategies.legacy_plugin_namespace import STRATEGY, detect
from dev10x.skills.doctor.strategy import Context


def _context(tmp_path: Path, data: dict) -> Context:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    return Context(settings_paths=(path,))


class TestDetection:
    def test_current_spellings_are_clean(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path,
            {
                "permissions": {"allow": ["Skill(dev10x:*)"], "deny": ["Skill(dev10x:x)"]},
                "enabledPlugins": {"dev10x@Dev10x-Guru": True},
            },
        )

        assert detect(context) == []

    def test_one_finding_per_move(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path,
            {
                "permissions": {"allow": ["Skill(Dev10x:*)"], "deny": ["Skill(Dev10x:x)"]},
                "enabledPlugins": {"Dev10x@Dev10x-Guru": True},
            },
        )

        locations = [finding.location.rsplit(":", 1)[1] for finding in detect(context)]

        assert locations == ["permissions.deny", "permissions.allow", "enabledPlugins"]

    def test_a_path_listed_twice_reports_once(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"permissions": {"deny": ["Skill(Dev10x:x)"]}})
        doubled = Context(settings_paths=context.settings_paths * 2)

        assert len(detect(doubled)) == 1

    @pytest.mark.parametrize("body", ["{not json", "[1, 2]"])
    def test_unreadable_files_are_skipped(self, tmp_path: Path, body: str) -> None:
        path = tmp_path / "settings.json"
        path.write_text(body)

        assert detect(Context(settings_paths=(path,))) == []


class TestSeverity:
    @pytest.mark.parametrize(
        ("list_name", "expected"),
        [("deny", "critical"), ("ask", "critical"), ("allow", "drift")],
    )
    def test_a_stale_guardrail_is_critical(
        self, tmp_path: Path, list_name: str, expected: str
    ) -> None:
        context = _context(tmp_path, {"permissions": {list_name: ["Skill(Dev10x:x)"]}})

        assert detect(context)[0].severity == expected

    def test_a_deny_whose_new_spelling_exists_is_drift(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path, {"permissions": {"deny": ["Skill(Dev10x:x)", "Skill(dev10x:x)"]}}
        )

        finding = detect(context)[0]

        assert finding.severity == "drift"
        assert "already in the list" in finding.evidence

    def test_the_evidence_says_what_stopped_working(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"permissions": {"deny": ["Skill(Dev10x:x)"]}})

        assert "guards nothing" in detect(context)[0].evidence


class TestRemediation:
    def test_rewrite_names_both_spellings(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path, {"permissions": {"deny": ["mcp__plugin_Dev10x_cli__merge_pr"]}}
        )
        finding = detect(context)[0]

        remediation = STRATEGY.remediate(finding)

        assert remediation.kind == "edit_settings"
        assert remediation.target == "permissions.deny"
        assert remediation.action == {
            "path": str(context.settings_paths[0]),
            "operation": "rewrite",
            "rule": "mcp__plugin_Dev10x_cli__merge_pr",
            "replacement": "mcp__plugin_dev10x_cli__merge_pr",
        }

    def test_duplicate_is_a_prune(self, tmp_path: Path) -> None:
        context = _context(
            tmp_path, {"permissions": {"allow": ["Skill(Dev10x:*)", "Skill(dev10x:*)"]}}
        )

        remediation = STRATEGY.remediate(detect(context)[0])

        assert remediation.action["operation"] == "prune"
        assert "Remove" in detect(context)[0].proposed_fix

    @pytest.mark.parametrize(
        ("plugins", "operation", "fix_word"),
        [
            ({"Dev10x@Dev10x-Guru": True}, "rewrite", "Rename"),
            ({"Dev10x@Dev10x-Guru": True, "dev10x@Dev10x-Guru": True}, "prune", "Remove"),
        ],
    )
    def test_plugin_id(self, tmp_path: Path, plugins: dict, operation: str, fix_word: str) -> None:
        finding = detect(_context(tmp_path, {"enabledPlugins": plugins}))[0]

        remediation = STRATEGY.remediate(finding)

        assert remediation.target == "enabledPlugins"
        assert remediation.action["operation"] == operation
        assert finding.proposed_fix.startswith(fix_word)
        assert finding.severity == "drift"


class TestRegistration:
    def test_the_doctor_loads_it_by_default(self) -> None:
        assert "legacy-plugin-namespace" in [strategy.id for strategy in load_strategies()]
