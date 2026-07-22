"""Tests for the shared read-only config I/O helper (ADR-0015, GH-828)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.config_io import ConfigIOError, load_json, load_yaml


class TestLoadYaml:
    def test_valid_mapping_is_returned(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"version": 1, "rules": []}), encoding="utf-8")
        assert load_yaml(path) == {"version": 1, "rules": []}

    def test_missing_file_non_strict_returns_empty(self, tmp_path: Path) -> None:
        assert load_yaml(tmp_path / "nope.yaml") == {}

    def test_missing_file_strict_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigIOError, match="not found"):
            load_yaml(tmp_path / "nope.yaml", strict=True)

    def test_malformed_yaml_non_strict_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("{not: valid: yaml:", encoding="utf-8")
        assert load_yaml(path) == {}

    def test_malformed_yaml_strict_raises_configioerror(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("{not: valid: yaml:", encoding="utf-8")
        with pytest.raises(ConfigIOError, match="Failed to parse"):
            load_yaml(path, strict=True)

    def test_non_mapping_non_strict_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(["a", "list"]), encoding="utf-8")
        assert load_yaml(path) == {}

    def test_non_mapping_strict_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(["a", "list"]), encoding="utf-8")
        with pytest.raises(ConfigIOError, match="not a mapping"):
            load_yaml(path, strict=True)

    def test_strict_error_chains_underlying_cause(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("{not: valid: yaml:", encoding="utf-8")
        with pytest.raises(ConfigIOError) as exc_info:
            load_yaml(path, strict=True)
        assert isinstance(exc_info.value.__cause__, yaml.YAMLError)


class TestLoadJson:
    def test_valid_mapping_is_returned(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"allow": ["Bash(ls:*)"]}), encoding="utf-8")
        assert load_json(path) == {"allow": ["Bash(ls:*)"]}

    def test_missing_file_non_strict_returns_empty(self, tmp_path: Path) -> None:
        assert load_json(tmp_path / "nope.json") == {}

    def test_missing_file_strict_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigIOError, match="not found"):
            load_json(tmp_path / "nope.json", strict=True)

    def test_malformed_json_non_strict_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert load_json(path) == {}

    def test_malformed_json_strict_raises_configioerror(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ConfigIOError, match="Failed to parse"):
            load_json(path, strict=True)

    def test_non_mapping_non_strict_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(["a", "list"]), encoding="utf-8")
        assert load_json(path) == {}

    def test_non_mapping_strict_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(["a", "list"]), encoding="utf-8")
        with pytest.raises(ConfigIOError, match="not a mapping"):
            load_json(path, strict=True)
