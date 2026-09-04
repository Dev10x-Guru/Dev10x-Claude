"""Tests for dev10x.config.loader — YAML config loading with msgpack cache."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import msgpack
import pytest
import yaml

from dev10x.config.loader import (
    _dict_to_config,
    _parse_yaml,
    _read_cache,
    _write_cache,
    load_config,
)


@pytest.fixture()
def yaml_path(tmp_path: Path) -> Path:
    return tmp_path / "config.yaml"


@pytest.fixture()
def cache_path(yaml_path: Path) -> Path:
    return yaml_path.with_suffix(".msgpack")


@pytest.fixture()
def minimal_yaml_content() -> dict:
    return {
        "config": {
            "plugin_repo": "https://github.com/example/repo",
        },
        "rules": [
            {
                "name": "block-push",
                "patterns": [r"^git\s+push"],
                "matcher": "Bash",
                "hook_block": True,
                "reason": "Use skill instead",
                "compensations": [
                    {
                        "type": "use-skill",
                        "skill": "Dev10x:git",
                        "description": "Use the git skill",
                    }
                ],
            }
        ],
    }


@pytest.fixture()
def yaml_file(yaml_path: Path, minimal_yaml_content: dict) -> Path:
    yaml_path.write_text(yaml.dump(minimal_yaml_content))
    return yaml_path


class TestParseYaml:
    def test_parses_config_section(self, yaml_file: Path) -> None:
        result = _parse_yaml(yaml_path=yaml_file)

        assert result.plugin_repo == "https://github.com/example/repo"

    def test_parses_rules(self, yaml_file: Path) -> None:
        result = _parse_yaml(yaml_path=yaml_file)

        assert len(result.rules) == 1
        assert result.rules[0].name == "block-push"
        assert result.rules[0].patterns == [r"^git\s+push"]

    def test_parses_compensations(self, yaml_file: Path) -> None:
        result = _parse_yaml(yaml_path=yaml_file)

        comp = result.rules[0].compensations[0]
        assert comp.type == "use-skill"
        assert comp.skill == "Dev10x:git"

    def test_defaults_for_empty_yaml(self, yaml_path: Path) -> None:
        yaml_path.write_text("")

        result = _parse_yaml(yaml_path=yaml_path)

        assert result.plugin_repo == ""
        assert result.rules == []

    def test_defaults_for_missing_fields(self, yaml_path: Path) -> None:
        yaml_path.write_text(yaml.dump({"rules": [{"name": "minimal"}]}))

        result = _parse_yaml(yaml_path=yaml_path)

        rule = result.rules[0]
        assert rule.name == "minimal"
        assert rule.patterns == []
        assert rule.matcher == "Bash"
        assert rule.hook_block is True


class TestWriteAndReadCache:
    def test_roundtrip(
        self,
        yaml_file: Path,
        cache_path: Path,
    ) -> None:
        config = _parse_yaml(yaml_path=yaml_file)

        _write_cache(cache_path=cache_path, config=config)
        result = _read_cache(
            cache_path=cache_path,
            yaml_path=yaml_file,
            ttl_seconds=3600,
        )

        assert result is not None
        assert result.plugin_repo == config.plugin_repo
        assert len(result.rules) == len(config.rules)
        assert result.rules[0].name == config.rules[0].name

    def test_roundtrip_preserves_match_position(
        self,
        yaml_file: Path,
        cache_path: Path,
    ) -> None:
        """GH-1084: a field the cache drops silently un-anchors the rule.

        The msgpack path rebuilds rules field-by-field, so an addition
        that reaches `from_yaml_entry` but not `_dict_to_config` works on
        a cold start and reverts on every cached load afterwards.
        """
        config = _parse_yaml(yaml_path=yaml_file)
        config.rules[0] = replace(config.rules[0], match_position="invocation")

        _write_cache(cache_path=cache_path, config=config)
        result = _read_cache(
            cache_path=cache_path,
            yaml_path=yaml_file,
            ttl_seconds=3600,
        )

        assert result is not None
        assert result.rules[0].match_position == "invocation"

    def test_returns_none_when_no_cache(
        self,
        cache_path: Path,
        yaml_file: Path,
    ) -> None:
        result = _read_cache(
            cache_path=cache_path,
            yaml_path=yaml_file,
            ttl_seconds=3600,
        )

        assert result is None

    def test_returns_none_when_yaml_newer(
        self,
        yaml_file: Path,
        cache_path: Path,
    ) -> None:
        config = _parse_yaml(yaml_path=yaml_file)
        _write_cache(cache_path=cache_path, config=config)

        future_time = time.time() + 10
        import os

        os.utime(yaml_file, (future_time, future_time))

        result = _read_cache(
            cache_path=cache_path,
            yaml_path=yaml_file,
            ttl_seconds=3600,
        )

        assert result is None

    def test_returns_none_when_ttl_expired(
        self,
        yaml_file: Path,
        cache_path: Path,
    ) -> None:
        config = _parse_yaml(yaml_path=yaml_file)
        _write_cache(cache_path=cache_path, config=config)

        result = _read_cache(
            cache_path=cache_path,
            yaml_path=yaml_file,
            ttl_seconds=0,
        )

        assert result is None


class TestLoadConfig:
    def test_loads_from_yaml_on_cache_miss(self, yaml_file: Path) -> None:
        result = load_config(yaml_path=yaml_file)

        assert result.plugin_repo == "https://github.com/example/repo"
        assert len(result.rules) == 1

    def test_creates_cache_after_first_load(
        self,
        yaml_file: Path,
        cache_path: Path,
    ) -> None:
        load_config(yaml_path=yaml_file)

        assert cache_path.exists()
        data = msgpack.unpackb(cache_path.read_bytes(), raw=False)
        assert data["plugin_repo"] == "https://github.com/example/repo"
        assert "friction_level" not in data

    def test_uses_cache_on_second_load(
        self,
        yaml_file: Path,
    ) -> None:
        first = load_config(yaml_path=yaml_file)
        second = load_config(yaml_path=yaml_file)

        assert first.plugin_repo == second.plugin_repo
        assert len(first.rules) == len(second.rules)


class TestDictToConfig:
    def test_converts_dict_with_rules(self) -> None:
        raw = {
            "plugin_repo": "https://example.com",
            "rules": [
                {
                    "name": "test-rule",
                    "patterns": ["^test"],
                    "compensations": [{"type": "use-skill", "skill": "test-skill"}],
                }
            ],
        }

        result = _dict_to_config(raw=raw)

        assert result.plugin_repo == "https://example.com"
        assert len(result.rules) == 1
        assert result.rules[0].compensations[0].skill == "test-skill"

    def test_defaults_for_missing_keys(self) -> None:
        result = _dict_to_config(raw={})

        assert result.plugin_repo == ""
        assert result.rules == []

    def test_stale_cache_carrying_friction_level_still_loads(self) -> None:
        """GH-1194: a msgpack cache written before the collapse must not raise.

        The cache is rewritten on any YAML change or TTL expiry, so
        ignoring the retired key is the whole migration — but ignoring it
        has to actually work, or every session with a warm cache breaks
        on upgrade.
        """
        raw = {
            "friction_level": "guided",
            "plugin_repo": "https://example.com",
            "rules": [],
        }

        result = _dict_to_config(raw=raw)

        assert result.plugin_repo == "https://example.com"
        assert not hasattr(result, "friction_level")
