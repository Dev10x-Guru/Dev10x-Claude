"""The `ask` policy tier — base_asks (GH-1154)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from dev10x.domain.common.policy import PolicyEffect
from dev10x.domain.common.policy_migration import migrate_flat_config
from dev10x.skills.permission import update_paths as mod
from dev10x.skills.permission.catalog_gap import compute_gap
from dev10x.skills.permission.policy_renderer import render_permissions


def _ask(path: Path) -> list[str]:
    return json.loads(path.read_text())["permissions"]["ask"]


def test_base_asks_migrate_to_ask_effect_policies() -> None:
    config = {"base_asks": ["Bash(gh api --method DELETE:*)"]}
    (policy,) = migrate_flat_config(config=config, baseline_policies=[])
    assert policy.effect is PolicyEffect.ASK


def test_render_permissions_exposes_ask_key() -> None:
    config = {"base_asks": ["Bash(gh api --method DELETE:*)"]}
    policies = migrate_flat_config(config=config, baseline_policies=[])
    rendered = render_permissions(policies=policies, home=str(Path.home()))
    assert rendered["ask"] == ["Bash(gh api --method DELETE:*)"]


def test_ensure_base_asks_adds_missing_rule(settings_file: Path) -> None:
    count, messages = mod.ensure_base_asks(
        settings_file,
        ["Bash(gh api --method DELETE:*)"],
        dry_run=False,
    )
    assert count == 1
    assert "Bash(gh api --method DELETE:*)" in _ask(settings_file)
    assert any("+ Bash(gh api --method DELETE:*)" in m for m in messages)


def test_ensure_base_asks_is_idempotent(settings_file: Path) -> None:
    mod.ensure_base_asks(settings_file, ["Bash(gh api --method DELETE:*)"], dry_run=False)
    count, messages = mod.ensure_base_asks(
        settings_file,
        ["Bash(gh api --method DELETE:*)"],
        dry_run=False,
    )
    assert count == 0
    assert messages == []
    assert _ask(settings_file) == ["Bash(gh api --method DELETE:*)"]


def test_ensure_base_asks_dry_run_writes_nothing(settings_file: Path) -> None:
    before = settings_file.read_text()
    count, messages = mod.ensure_base_asks(
        settings_file,
        ["Bash(gh api --method DELETE:*)"],
        dry_run=True,
    )
    assert count == 1
    assert messages != []
    assert settings_file.read_text() == before


def test_ensure_base_asks_skips_rule_already_denied(settings_file: Path) -> None:
    settings_file.write_text(
        json.dumps({"permissions": {"deny": ["Bash(gh api --method DELETE:*)"]}})
    )
    count, messages = mod.ensure_base_asks(
        settings_file,
        ["Bash(gh api --method DELETE:*)"],
        dry_run=False,
    )
    assert count == 0
    assert any("skipped 1 already denied by this file" in m for m in messages)
    data = json.loads(settings_file.read_text())
    assert "ask" not in data.get("permissions", {})


def test_ensure_base_asks_reports_partial_skip_alongside_added(settings_file: Path) -> None:
    settings_file.write_text(
        json.dumps({"permissions": {"deny": ["Bash(gh api --method DELETE:*)"]}})
    )
    count, messages = mod.ensure_base_asks(
        settings_file,
        ["Bash(gh api --method DELETE:*)", "Bash(gh api --method PATCH:*)"],
        dry_run=False,
    )
    assert count == 1
    assert "Bash(gh api --method PATCH:*)" in _ask(settings_file)
    assert any("skipped 1 already denied by this file" in m for m in messages)


def test_compute_gap_reports_missing_ask(settings_file: Path) -> None:
    gap = compute_gap(
        path=settings_file,
        base_permissions=[],
        base_denies=[],
        base_asks=["Bash(gh api --method DELETE:*)"],
    )
    assert gap.missing_ask == ["Bash(gh api --method DELETE:*)"]
    assert gap.total_missing == 1
    assert not gap.is_empty


def test_compute_gap_without_base_asks_reports_empty_ask_gap(settings_file: Path) -> None:
    """Back-compat: an omitted base_asks arg is never treated as all-missing."""
    gap = compute_gap(
        path=settings_file,
        base_permissions=[],
        base_denies=[],
    )
    assert gap.missing_ask == []
    assert gap.is_empty


def test_shipped_catalog_populates_the_ask_tier(projects_yaml: Path) -> None:
    config = yaml.safe_load(projects_yaml.read_text(encoding="utf-8"))
    base_asks = config["base_asks"]
    assert base_asks
    assert all(rule.startswith("Bash(gh api ") for rule in base_asks)


def test_shipped_catalog_guards_gh_api_delete(projects_yaml: Path) -> None:
    config = yaml.safe_load(projects_yaml.read_text(encoding="utf-8"))
    assert "Bash(gh api -X DELETE:*)" in config["base_asks"]
