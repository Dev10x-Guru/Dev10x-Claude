"""GH-1503: ``clean`` repairs `*`-before-`:*` rules in every settings layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import clean_project_files as clean_mod

USER_SETTINGS = {
    "permissions": {
        "allow": ["Bash(~/.claude/tools/*:*)", "Bash(git log:*)"],
        "deny": ["Bash(mv * /dev/null:*)"],
        "ask": ["Bash(rm -rf /work/**:*)"],
    }
}

REPAIRED = {
    "allow": ["Bash(git log:*)"],
    "deny": ["Bash(mv * /dev/null*)"],
    "ask": ["Bash(rm -rf /work/**)"],
}


@pytest.fixture
def user_settings(tmp_path: Path) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(USER_SETTINGS) + "\n")
    return path


@pytest.fixture
def project_settings(tmp_path: Path) -> Path:
    path = tmp_path / "project" / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(USER_SETTINGS) + "\n")
    return path


def _permissions(path: Path) -> dict:
    return json.loads(path.read_text())["permissions"]


def _clean(path: Path, *, dry_run: bool = False) -> tuple:
    return clean_mod.clean_file(path, global_rules=set(), current_version=None, dry_run=dry_run)


class TestUserLayer:
    def test_allows_drop_and_guardrails_rewrite(self, user_settings: Path) -> None:
        result, _ = clean_mod.migrate_file(user_settings)

        assert _permissions(user_settings) == REPAIRED
        assert result.star_prefix_repair.count == 3

    def test_every_change_is_reported(self, user_settings: Path) -> None:
        _, messages = clean_mod.migrate_file(user_settings, dry_run=True)

        assert messages == [
            "  - 3 rules with `*` before `:*` repaired (GH-1503)",
            "    deny: Bash(mv * /dev/null:*) -> Bash(mv * /dev/null*)",
            "    ask: Bash(rm -rf /work/**:*) -> Bash(rm -rf /work/**)",
            "    allow: dropped Bash(~/.claude/tools/*:*) "
            "(a `*` before `:*` never matches; the space form would widen it)",
        ]

    def test_dry_run_does_not_write(self, user_settings: Path) -> None:
        original = user_settings.read_text()

        clean_mod.migrate_file(user_settings, dry_run=True)

        assert user_settings.read_text() == original

    def test_second_run_is_a_no_op(self, user_settings: Path) -> None:
        clean_mod.migrate_file(user_settings)
        after_first = user_settings.read_text()

        result, messages = clean_mod.migrate_file(user_settings)

        assert user_settings.read_text() == after_first
        assert result.repaired is False
        assert messages == []


class TestProjectLayer:
    def test_repair_lands_beside_pruning(self, project_settings: Path) -> None:
        result, _ = _clean(project_settings)

        assert _permissions(project_settings) == REPAIRED
        assert result.star_prefix_repair.count == 3

    def test_second_run_is_a_no_op(self, project_settings: Path) -> None:
        _clean(project_settings)
        after_first = project_settings.read_text()

        result, messages = _clean(project_settings)

        assert project_settings.read_text() == after_first
        assert result.repaired is False
        assert messages == []

    def test_a_guardrail_only_file_is_repaired(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"ask": ["Bash(cp * ~/.claude:*)"]}}))

        _clean(path)

        assert _permissions(path) == {"ask": ["Bash(cp * ~/.claude*)"]}


class TestRunClean:
    def test_repairs_are_counted_per_layer(
        self, user_settings: Path, project_settings: Path
    ) -> None:
        run = clean_mod.run_clean(
            settings_files=[project_settings],
            global_rules=set(),
            current_version=None,
            base_permissions=set(),
            cache_root=None,
            dry_run=False,
            verbose=False,
            skip_global_dedup=True,
            migration_layers=[user_settings],
        )

        assert run.total_star_repaired == 6
        assert run.files_changed == 2
