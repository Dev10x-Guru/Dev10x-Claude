"""Tests for dev10x.hooks.edit_validator — Edit/Write tool validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.rules.rule_engine import RuleEngine
from dev10x.domain.rules.validation_rule import Rule


@pytest.fixture()
def rule_with_pattern() -> Rule:
    return Rule(
        name="block-env",
        file_pattern=r"\.env$",
        message="BLOCKED: {file_path}",
    )


@pytest.fixture()
def rule_with_names() -> Rule:
    return Rule(
        name="block-secrets",
        file_names=["credentials.json", "secrets.yaml"],
        message="BLOCKED: sensitive file",
    )


@pytest.fixture()
def rule_with_prefixes() -> Rule:
    return Rule(
        name="block-dot-env",
        file_prefixes=[".env"],
        message="BLOCKED: env file",
    )


@pytest.fixture()
def rule_with_substrings() -> Rule:
    return Rule(
        name="block-secret-dirs",
        file_substrings=["/secrets/"],
        message="BLOCKED: secrets directory",
    )


@pytest.fixture()
def rule_with_content_pattern() -> Rule:
    return Rule(
        name="block-eval",
        file_pattern=r"SKILL\.md$",
        content_pattern=r"\beval\b",
        message="BLOCKED: eval in skill",
    )


class TestMatchesFile:
    def test_matches_file_pattern(
        self,
        rule_with_pattern: Rule,
    ) -> None:
        assert rule_with_pattern.matches_file(file_path="/work/.env") is True

    def test_rejects_non_matching_pattern(
        self,
        rule_with_pattern: Rule,
    ) -> None:
        assert rule_with_pattern.matches_file(file_path="/work/main.py") is False

    def test_matches_file_names(
        self,
        rule_with_names: Rule,
    ) -> None:
        assert rule_with_names.matches_file(file_path="/work/credentials.json") is True

    def test_rejects_non_matching_names(
        self,
        rule_with_names: Rule,
    ) -> None:
        assert rule_with_names.matches_file(file_path="/work/config.json") is False

    def test_matches_file_prefixes(
        self,
        rule_with_prefixes: Rule,
    ) -> None:
        assert rule_with_prefixes.matches_file(file_path="/work/.env.production") is True

    def test_matches_file_substrings(
        self,
        rule_with_substrings: Rule,
    ) -> None:
        assert (
            rule_with_substrings.matches_file(
                file_path="/work/secrets/api.key",
            )
            is True
        )


class TestMatchesContent:
    def test_matches_when_no_content_pattern(
        self,
        rule_with_pattern: Rule,
    ) -> None:
        assert rule_with_pattern.matches_content(content="anything") is True

    def test_matches_content_pattern(
        self,
        rule_with_content_pattern: Rule,
    ) -> None:
        assert rule_with_content_pattern.matches_content(content="eval(code)") is True

    def test_rejects_non_matching_content(
        self,
        rule_with_content_pattern: Rule,
    ) -> None:
        assert rule_with_content_pattern.matches_content(content="safe code") is False


class TestFormatMessage:
    def test_formats_file_path(self, rule_with_pattern: Rule) -> None:
        result = rule_with_pattern.format_message(file_path="/work/.env")

        assert result == "BLOCKED: /work/.env"

    def test_appends_compensation_descriptions(self) -> None:
        from dev10x.domain.rules.validation_rule import Compensation

        rule = Rule(
            name="test",
            message="BLOCKED",
            compensations=[
                Compensation(type="use-skill", description="Use the Write tool instead")
            ],
        )

        result = rule.format_message(file_path="/work/file.py")

        assert "Use the Write tool instead" in result


class TestLoadRules:
    def test_loads_edit_write_rules(self, tmp_path: Path) -> None:
        yaml_content = {
            "rules": [
                {
                    "name": "block-env",
                    "matcher": "Edit|Write",
                    "hook_block": True,
                    "file_names": [".env"],
                    "reason": "Sensitive file",
                },
                {
                    "name": "bash-rule",
                    "matcher": "Bash",
                    "hook_block": True,
                    "patterns": ["^git push"],
                },
            ]
        }
        yaml_path = tmp_path / "rules.yaml"
        yaml_path.write_text(yaml.dump(yaml_content))

        engine = RuleEngine.from_yaml(path=yaml_path)

        assert len(engine.edit_rules) == 1
        assert engine.edit_rules[0].name == "block-env"

    def test_skips_non_blocking_rules(self, tmp_path: Path) -> None:
        yaml_content = {
            "rules": [
                {
                    "name": "advisory",
                    "matcher": "Edit|Write",
                    "hook_block": False,
                    "file_names": [".env"],
                },
            ]
        }
        yaml_path = tmp_path / "rules.yaml"
        yaml_path.write_text(yaml.dump(yaml_content))

        engine = RuleEngine.from_yaml(path=yaml_path)

        assert len(engine.edit_rules) == 0
