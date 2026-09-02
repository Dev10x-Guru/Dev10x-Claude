"""Doctor strategy: $HOME / ~/.claude registered as a work dir (GH-1140)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.registry import DEFAULT_STRATEGY_MODULES, load_strategies
from dev10x.skills.doctor.strategies import home_in_additional_directories as strategy
from dev10x.skills.doctor.strategy import Context


@pytest.fixture
def settings(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def _write(path: Path, directories: list[str]) -> None:
    path.write_text(json.dumps({"permissions": {"additionalDirectories": directories}}))


def test_strategy_is_registered():
    assert "dev10x.skills.doctor.strategies.home_in_additional_directories" in (
        DEFAULT_STRATEGY_MODULES
    )
    assert any(s.id == "home-in-additional-directories" for s in load_strategies())


@pytest.mark.parametrize("entry", ["~/.claude", "~/.claude/", "~"])
def test_flags_overreaching_entry(settings: Path, entry: str):
    _write(settings, [entry])
    findings = strategy.detect(Context(settings_paths=(settings,)))
    assert len(findings) == 1
    assert findings[0].severity == "critical"
    assert entry in findings[0].evidence


@pytest.mark.parametrize(
    "entry",
    ["~/.claude/memory", "~/.claude/plugins", "~/.config/Dev10x", "/tmp/Dev10x"],
)
def test_narrow_grants_are_not_flagged(settings: Path, entry: str):
    _write(settings, [entry])
    assert strategy.detect(Context(settings_paths=(settings,))) == []


def test_absolute_home_path_is_flagged(settings: Path):
    _write(settings, [str(Path.home() / ".claude")])
    assert len(strategy.detect(Context(settings_paths=(settings,)))) == 1


def test_missing_or_malformed_file_yields_no_finding(tmp_path: Path):
    absent = tmp_path / "absent.json"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json")
    context = Context(settings_paths=(absent, malformed))
    assert strategy.detect(context) == []


def test_remediation_proposes_removal(settings: Path):
    _write(settings, ["~/.claude"])
    finding = strategy.detect(Context(settings_paths=(settings,)))[0]
    remediation = strategy.remediate(finding)
    assert remediation.kind == "edit_settings"
    assert remediation.action["remove"] == "~/.claude"
    assert remediation.target == str(settings)
