"""GH-1711: the doctor lists grants only some checkouts of a repo hold."""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.skills.doctor.registry import load_strategies
from dev10x.skills.doctor.strategies import sibling_only_grants
from dev10x.skills.doctor.strategies.sibling_only_grants import GRANT_TOOL, STRATEGY, detect
from dev10x.skills.doctor.strategy import Context, Finding
from dev10x.skills.permission.declined_catalog import decline_rules
from dev10x.skills.permission.granted_catalog import granted_path, remember_granted_rule

from tests.skills.doctor.conftest import WriteSettings


@pytest.fixture
def family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_settings: WriteSettings
) -> tuple[Path, Path, Path]:
    main = tmp_path / "repo"
    wt1 = tmp_path / ".herdr" / "worktrees" / "repo" / "wt-1"
    wt2 = tmp_path / ".herdr" / "worktrees" / "repo" / "wt-2"
    write_settings(checkout=main, allow=["Bash(git log:*)"])
    write_settings(checkout=wt1, allow=["Bash(git log:*)", "Bash(npm ci:*)", "Bash(bash:*)"])
    write_settings(checkout=wt2, allow=["Bash(git log:*)", f"Bash({wt2}/bin/x.sh:*)"])
    monkeypatch.setattr(
        sibling_only_grants, "git_registered_worktrees", lambda _c: [main, wt1, wt2]
    )
    return main, wt1, wt2


def _context(*checkouts: Path) -> Context:
    return Context(settings_paths=tuple(c / ".claude" / "settings.local.json" for c in checkouts))


@pytest.fixture
def finding(family: tuple[Path, Path, Path]) -> Finding:
    [only] = detect(_context(family[0]))
    return only


@pytest.fixture
def remembered(family: tuple[Path, Path, Path]) -> tuple[Path, Path, Path]:
    remember_granted_rule(rule="Bash(npm ci:*)")
    return family


@pytest.fixture
def declined(family: tuple[Path, Path, Path]) -> tuple[Path, Path, Path]:
    decline_rules(rules=["Bash(npm ci:*)"])
    return family


def test_sibling_only_rule_is_reported(finding: Finding, family: tuple[Path, Path, Path]) -> None:
    assert finding.location == "Bash(npm ci:*)"
    assert finding.severity == "suggestion"
    assert f"1 of 3 checkouts ({family[1]})" in finding.evidence


def test_remediation_lifts_through_permission_grant(finding: Finding) -> None:
    remediation = STRATEGY.remediate(finding)

    assert remediation.target == str(granted_path())
    assert remediation.action == {
        "tool": GRANT_TOOL,
        "arguments": {"target": "Bash(npm ci:*)", "rule": "Bash(npm ci:*)", "remember": True},
    }


def test_two_checkouts_of_one_family_report_once(family: tuple[Path, Path, Path]) -> None:
    assert [f.location for f in detect(_context(family[0], family[1]))] == ["Bash(npm ci:*)"]


def test_remembered_rule_is_not_reported(remembered: tuple[Path, Path, Path]) -> None:
    assert detect(_context(remembered[0])) == []


def test_declined_rule_is_not_reported(declined: tuple[Path, Path, Path]) -> None:
    assert detect(_context(declined[0])) == []


def test_lone_checkout_has_no_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_settings: WriteSettings
) -> None:
    main = tmp_path / "repo"
    write_settings(checkout=main, allow=["Bash(npm ci:*)"])
    monkeypatch.setattr(sibling_only_grants, "git_registered_worktrees", lambda _c: [main])

    assert detect(_context(main)) == []


def test_user_scope_only_context_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{}")

    assert detect(Context(settings_paths=(path,))) == []


def test_strategy_is_registered() -> None:
    assert STRATEGY.id in [strategy.id for strategy in load_strategies()]
