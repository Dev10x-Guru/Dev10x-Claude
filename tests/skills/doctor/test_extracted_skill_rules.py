"""GH-1571: the doctor flags rules naming a skill by its pre-extraction name."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.core.plugin_map import PluginMap
from dev10x.core.skills.doctor.registry import load_strategies
from dev10x.core.skills.doctor.strategies.extracted_skill_rules import (
    STRATEGY,
    detect,
    detect_with_map,
    replacement_for,
)
from dev10x.core.skills.doctor.strategy import Context, Finding

PLUGIN_MAP = PluginMap(
    plugins={"core": ("afk",), "tasks": ("park",), "coding": ("work-on",)},
    plugin_names={"core": "dev10x", "tasks": "dev10x-tasks", "coding": "dev10x-coding"},
    marketplace="Dev10x-Guru",
    extracted=("tasks",),
)


def _context(tmp_path: Path, permissions: dict[str, list[str]]) -> Context:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"permissions": permissions}))
    return Context(settings_paths=(path,))


def _detect(context: Context) -> list[Finding]:
    return detect_with_map(context, plugin_map=PLUGIN_MAP)


class TestReplacement:
    @pytest.mark.parametrize(
        ("rule", "expected"),
        [
            ("Skill(dev10x:park)", "Skill(dev10x-tasks:park)"),
            ("Skill(dev10x:park:*)", "Skill(dev10x-tasks:park:*)"),
            ("Skill(dev10x:afk)", None),
            ("Skill(dev10x:work-on)", None),
            ("Skill(dev10x:*)", None),
            ("Skill(dev10x:unknown)", None),
            ("Skill(dev10x-tasks:park)", None),
            ("Bash(dev10x:park)", None),
        ],
    )
    def test_only_extracted_skills_move(self, rule: str, expected: str | None) -> None:
        assert replacement_for(rule=rule, plugin_map=PLUGIN_MAP) == expected


class TestDetection:
    def test_current_spellings_are_clean(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"allow": ["Skill(dev10x-tasks:park)", "Skill(dev10x:afk)"]})

        assert _detect(context) == []

    @pytest.mark.parametrize(
        ("list_name", "expected"),
        [("deny", "critical"), ("ask", "critical"), ("allow", "drift")],
    )
    def test_a_stale_guardrail_is_critical(
        self, tmp_path: Path, list_name: str, expected: str
    ) -> None:
        context = _context(tmp_path, {list_name: ["Skill(dev10x:park)"]})

        assert [finding.severity for finding in _detect(context)] == [expected]

    def test_a_path_listed_twice_reports_once(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"deny": ["Skill(dev10x:park)"]})
        doubled = Context(settings_paths=context.settings_paths * 2)

        assert len(_detect(doubled)) == 1

    @pytest.mark.parametrize(
        "body", ["{not json", "[1, 2]", '{"permissions": []}', '{"permissions": {"allow": 3}}']
    )
    def test_unreadable_files_are_skipped(self, tmp_path: Path, body: str) -> None:
        path = tmp_path / "settings.json"
        path.write_text(body)

        assert _detect(Context(settings_paths=(path,))) == []

    def test_non_string_rules_are_ignored(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"allow": [3, "Skill(dev10x:park)"]})  # type: ignore[list-item]

        assert len(_detect(context)) == 1


class TestRemediation:
    def test_rewrite_names_both_spellings(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"deny": ["Skill(dev10x:park)"]})

        remediation = STRATEGY.remediate(_detect(context)[0])

        assert remediation.kind == "edit_settings"
        assert remediation.target == "permissions.deny"
        assert remediation.action == {
            "path": str(context.settings_paths[0]),
            "operation": "rewrite",
            "rule": "Skill(dev10x:park)",
            "replacement": "Skill(dev10x-tasks:park)",
        }

    def test_a_duplicate_is_a_prune(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"deny": ["Skill(dev10x:park)", "Skill(dev10x-tasks:park)"]})

        finding = _detect(context)[0]

        assert finding.severity == "drift"
        assert finding.proposed_fix.startswith("Remove")
        assert STRATEGY.remediate(finding).action["operation"] == "prune"


class TestShippedMap:
    def test_detect_reads_the_shipped_map(self, tmp_path: Path) -> None:
        context = _context(tmp_path, {"allow": ["Skill(dev10x:park)"]})

        assert [finding.proposed_fix for finding in detect(context)] == [
            "Rewrite to ``Skill(dev10x-tasks:park)``."
        ]


class TestRegistration:
    def test_the_doctor_loads_it_by_default(self) -> None:
        assert "extracted-skill-rules" in [strategy.id for strategy in load_strategies()]
