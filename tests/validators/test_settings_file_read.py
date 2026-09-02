"""The settings-file-read map entry and its non-firing paths (GH-1140)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "dev10x"
    / "validators"
    / "command-skill-map.yaml"
)


def _rule(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(_YAML_PATH.read_text()) or {}
    for entry in data.get("rules", []):
        if entry.get("name") == name:
            return entry
    raise AssertionError(f"rule {name!r} not found in command-skill-map.yaml")


@pytest.fixture(scope="module")
def settings_read_rule() -> dict[str, Any]:
    return _rule("settings-file-read")


@pytest.fixture(scope="module")
def patterns(settings_read_rule: dict[str, Any]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in settings_read_rule["patterns"]]


def _matches(patterns: list[re.Pattern[str]], command: str) -> bool:
    return any(p.search(command) for p in patterns)


def test_entry_blocks_deterministically(settings_read_rule: dict[str, Any]):
    """An un-allow-listable shape must deny, not advise after the prompt."""
    assert settings_read_rule["hook_block"] is True


def test_entry_names_both_sanctioned_surfaces(settings_read_rule: dict[str, Any]):
    tools = {c.get("tool") for c in settings_read_rule["compensations"]}
    assert "Read" in tools
    assert "mcp__plugin_Dev10x_cli__audit_analyze_permissions" in tools


@pytest.mark.parametrize(
    "command",
    [
        'rg -c "permissions" ~/.claude/settings.json',
        "grep allow ~/.claude/settings.local.json",
        "cat ~/.claude/settings.json",
        "jq '.permissions.allow' ~/.claude/settings.json",
        "head -50 .claude/settings.local.json",
        "tail -20 .claude/settings.json",
        "awk '/allow/' ~/.claude/settings.json",
        "sed -n '1,5p' ~/.claude/settings.local.json",
    ],
)
def test_fires_on_settings_reads(patterns: list[re.Pattern[str]], command: str):
    assert _matches(patterns, command)


@pytest.mark.parametrize(
    "command",
    [
        "rg -c tracker ~/.config/Dev10x/projects.yaml",
        "cat ~/.config/Dev10x/friction.yaml",
        "rg allow src/dev10x/validators/command-skill-map.yaml",
        "cat package.json",
        "jq empty skills/diag-friction/evals/evals.json",
        "rg settings src/dev10x/permission/service.py",
    ],
)
def test_does_not_fire_on_unrelated_paths(patterns: list[re.Pattern[str]], command: str):
    """~/.config/Dev10x and repo paths are registered — they must stay clean."""
    assert not _matches(patterns, command)


def test_find_search_reason_is_scoped_to_registered_directories():
    """The unconditional 'always available under Bash(rg:*)' claim was false
    for paths outside additionalDirectories — the same defect class GH-1087
    fixed for Glob."""
    alternatives = [
        c for c in _rule("find-search")["compensations"] if c.get("type") == "use-alternative"
    ]
    assert alternatives, "find-search lost its unconditional rg alternative"
    text = alternatives[0]["description"]
    assert "additionalDirectories" in text
    assert "settings-file-read" in text
