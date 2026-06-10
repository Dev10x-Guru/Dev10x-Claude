"""Tests for the shared permission config loader (GH-246 H12, GH-532)."""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.permission.config import parse_config, resolve_config


class TestResolveConfig:
    def test_returns_first_existing_candidate(self, tmp_path: Path):
        first = tmp_path / "first.yaml"
        second = tmp_path / "second.yaml"
        first.write_text("a: 1")
        second.write_text("b: 2")
        assert resolve_config(candidates=[first, second]) == SuccessResult(value=first)

    def test_skips_missing_candidates(self, tmp_path: Path):
        missing = tmp_path / "missing.yaml"
        present = tmp_path / "present.yaml"
        present.write_text("a: 1")
        assert resolve_config(candidates=[missing, present]) == SuccessResult(value=present)

    def test_errs_with_generic_message_when_none_found(self, tmp_path: Path):
        result = resolve_config(candidates=[tmp_path / "nope.yaml"])
        assert result == ErrorResult(error="No config found.")

    def test_errs_with_create_hint_when_provided(self, tmp_path: Path):
        create = tmp_path / "make-me.yaml"
        plugin = tmp_path / "plugin.yaml"
        result = resolve_config(candidates=[create, plugin], create_path=create)
        assert isinstance(result, ErrorResult)
        assert str(create) in result.error
        assert str(plugin) in result.error

    def test_logs_error_when_none_found(self, tmp_path: Path, caplog):
        with caplog.at_level("ERROR", logger="dev10x.skills.permission.config"):
            resolve_config(candidates=[tmp_path / "nope.yaml"])
        assert "No config found." in caplog.text


class TestParseConfig:
    def test_parses_yaml_into_dict(self, tmp_path: Path):
        config = tmp_path / "c.yaml"
        config.write_text("roots:\n  - /a\n  - /b\n")
        assert parse_config(config_path=config) == {"roots": ["/a", "/b"]}
