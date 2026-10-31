"""A remembered grant reaches checkouts created after it (GH-1677)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import LockTimeoutError
from dev10x.skills.permission.catalog_write import seed_worktree
from dev10x.skills.permission.granted_catalog import (
    load_granted_rules,
    remember_granted_rule,
    with_granted_rules,
)

from dev10x.skills.permission import catalog_load, enumerate_mcp, granted_catalog

RULE = "Bash(npm ci:*)"


@pytest.fixture
def granted_file() -> Path:
    return Dev10xConfigDir.granted_permissions_yaml()


class TestRememberGrantedRule:
    def test_first_rule_creates_the_file(self, granted_file: Path) -> None:
        result = remember_granted_rule(rule=RULE)

        assert isinstance(result, SuccessResult)
        assert result.value == {"path": str(granted_file), "rule": RULE, "added": True}
        assert yaml.safe_load(granted_file.read_text()) == {"base_permissions": [RULE]}

    def test_remembering_twice_is_idempotent(self, granted_file: Path) -> None:
        remember_granted_rule(rule=RULE)

        result = remember_granted_rule(rule=f"  {RULE}  ")

        assert isinstance(result, SuccessResult)
        assert result.value["added"] is False
        assert load_granted_rules() == [RULE]

    def test_rules_accumulate_in_order(self) -> None:
        remember_granted_rule(rule=RULE)
        remember_granted_rule(rule="Bash(uptime:*)")

        assert load_granted_rules() == [RULE, "Bash(uptime:*)"]

    @pytest.mark.parametrize(
        ("rule", "message"),
        [("   ", "empty rule"), ("Bash(~/tools/*.py:*)", "never matches")],
        ids=["blank", "star-before-colon-star"],
    )
    def test_refuses_a_rule_that_cannot_work(
        self,
        granted_file: Path,
        rule: str,
        message: str,
    ) -> None:
        result = remember_granted_rule(rule=rule)

        assert isinstance(result, ErrorResult)
        assert message in result.error
        assert not granted_file.exists()

    def test_a_held_lock_reports_try_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _locked(_path: Path) -> None:
            raise LockTimeoutError("held")

        monkeypatch.setattr(granted_catalog, "locked_yaml_update", _locked)

        result = remember_granted_rule(rule=RULE)

        assert isinstance(result, ErrorResult)
        assert "please try again" in result.error


class TestRememberGrantedRuleFailures:
    """Every failure comes back as an err naming the file, never a raise."""

    @pytest.fixture
    def written(self, granted_file: Path) -> Path:
        granted_file.parent.mkdir(parents=True, exist_ok=True)
        return granted_file

    @pytest.mark.parametrize(
        ("content", "message"),
        [(": not yaml: [", "not valid YAML"), ("- a list\n", "is not a mapping")],
        ids=["corrupt-yaml", "not-a-mapping"],
    )
    def test_bad_file_is_reported_and_left_untouched(
        self,
        written: Path,
        content: str,
        message: str,
    ) -> None:
        written.write_text(content)

        result = remember_granted_rule(rule=RULE)

        assert isinstance(result, ErrorResult)
        assert message in result.error
        assert str(written) in result.error
        assert written.read_text() == content

    def test_os_error_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _refuse(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(Path, "mkdir", _refuse)

        result = remember_granted_rule(rule=RULE)

        assert isinstance(result, ErrorResult)
        assert "read-only" in result.error


class TestLoadGrantedRules:
    def test_absent_file_is_no_rules(self) -> None:
        assert load_granted_rules() == []

    @pytest.mark.parametrize(
        "content",
        [": not yaml: [", "- a list\n", "base_permissions: nope\n"],
        ids=["invalid-yaml", "not-a-mapping", "not-a-list"],
    )
    def test_malformed_file_is_no_rules(self, granted_file: Path, content: str) -> None:
        granted_file.parent.mkdir(parents=True, exist_ok=True)
        granted_file.write_text(content)

        assert load_granted_rules() == []

    def test_non_string_entries_are_dropped(self, granted_file: Path) -> None:
        granted_file.parent.mkdir(parents=True, exist_ok=True)
        granted_file.write_text(yaml.safe_dump({"base_permissions": [RULE, 3, "", None]}))

        assert load_granted_rules() == [RULE]


class TestWithGrantedRules:
    def test_appends_only_new_rules(self) -> None:
        config = {"base_permissions": ["Bash(ls:*)", RULE], "roots": ["/w"]}

        merged = with_granted_rules(config=config, granted=[RULE, "Bash(uptime:*)"])

        assert merged == {
            "base_permissions": ["Bash(ls:*)", RULE, "Bash(uptime:*)"],
            "roots": ["/w"],
        }
        assert config["base_permissions"] == ["Bash(ls:*)", RULE]

    def test_without_grants_returns_config_unchanged(self) -> None:
        config = {"roots": []}

        assert with_granted_rules(config=config, granted=[]) is config

    def test_config_without_allow_tier_gains_one(self) -> None:
        assert with_granted_rules(config={}, granted=[RULE]) == {"base_permissions": [RULE]}


class TestPropagation:
    """The remembered layer reaches seeding without a new code path."""

    @pytest.fixture
    def user_catalog(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "projects.yaml"
        path.write_text(yaml.safe_dump({"roots": [], "base_permissions": ["Bash(ls:*)"]}))
        monkeypatch.setattr(catalog_load, "load_shipped_config", lambda: None)
        monkeypatch.setattr(enumerate_mcp, "discover_mcp_tools", lambda **_kw: {})
        return path

    def test_effective_config_carries_remembered_rules(self, user_catalog: Path) -> None:
        remember_granted_rule(rule=RULE)

        config = catalog_load.load_effective_config(user_catalog).config

        assert config["base_permissions"] == ["Bash(ls:*)", RULE]

    def test_a_worktree_seeded_later_receives_the_grant(
        self,
        user_catalog: Path,
        tmp_path: Path,
    ) -> None:
        remember_granted_rule(rule=RULE)
        worktree = tmp_path / "wt-new"
        worktree.mkdir()

        result = seed_worktree(
            worktree_root=worktree,
            config=catalog_load.load_effective_config(user_catalog).config,
        )

        assert isinstance(result, SuccessResult)
        settings = json.loads((worktree / ".claude" / "settings.local.json").read_text())
        assert RULE in settings["permissions"]["allow"]
