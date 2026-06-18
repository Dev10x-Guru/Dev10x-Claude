"""Tests for the shared baseline-catalog loader (GH-587)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.baseline_catalog import load_baseline_dict


class TestLoadBaselineDict:
    def test_valid_mapping_is_returned(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.yaml"
        path.write_text(
            yaml.safe_dump({"version": 1, "groups": {}}),
            encoding="utf-8",
        )
        assert load_baseline_dict(path) == {"version": 1, "groups": {}}

    def test_missing_file_non_strict_returns_empty(self, tmp_path: Path) -> None:
        assert load_baseline_dict(tmp_path / "nope.yaml") == {}

    def test_missing_file_strict_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_baseline_dict(tmp_path / "nope.yaml", strict=True)

    def test_malformed_yaml_non_strict_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.yaml"
        path.write_text("{not: valid: yaml:", encoding="utf-8")
        assert load_baseline_dict(path) == {}

    def test_malformed_yaml_strict_propagates(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.yaml"
        path.write_text("{not: valid: yaml:", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_baseline_dict(path, strict=True)

    def test_non_mapping_non_strict_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.yaml"
        path.write_text(yaml.safe_dump(["a", "list"]), encoding="utf-8")
        assert load_baseline_dict(path) == {}

    def test_non_mapping_strict_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.yaml"
        path.write_text(yaml.safe_dump(["a", "list"]), encoding="utf-8")
        with pytest.raises(ValueError, match="not a mapping"):
            load_baseline_dict(path, strict=True)
