"""Tests for dev10x.hooks.edit_validator — Edit/Write tool validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from dev10x.domain.rules.rule_engine import RuleEngine
from dev10x.domain.rules.validation_rule import Rule
from dev10x.hooks.edit_validator import _build_engine, reset_engine_cache


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


class TestBuildEngineCache:
    """GH-586: _build_engine caches by (path, mtime) to avoid re-parsing
    the YAML config on every Edit/Write hook invocation."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        reset_engine_cache()
        yield
        reset_engine_cache()

    def _write_yaml(self, path: Path, rule_name: str) -> None:
        path.write_text(
            yaml.dump(
                {
                    "rules": [
                        {
                            "name": rule_name,
                            "matcher": "Edit|Write",
                            "hook_block": True,
                            "file_names": [".env"],
                        }
                    ]
                }
            )
        )

    def test_same_file_returns_cached_engine(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "rules.yaml"
        self._write_yaml(yaml_path, "block-env")
        first = _build_engine(yaml_path=yaml_path)
        second = _build_engine(yaml_path=yaml_path)
        assert first is second

    def test_changed_mtime_rebuilds_engine(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "rules.yaml"
        self._write_yaml(yaml_path, "block-env")
        first = _build_engine(yaml_path=yaml_path)
        # Simulate an edit by bumping the file's mtime forward.
        st = yaml_path.stat()
        os.utime(yaml_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        second = _build_engine(yaml_path=yaml_path)
        assert first is not second

    def test_missing_config_bypasses_cache_and_raises(self, tmp_path: Path) -> None:
        # stat() on a missing file raises OSError → sentinel mtime branch;
        # load_config then surfaces the error as before (no silent cache).
        with pytest.raises(Exception):
            _build_engine(yaml_path=tmp_path / "does-not-exist.yaml")
