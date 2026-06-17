"""Tests for queryable rule provenance (GH-602)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.permission.provenance import (
    RuleProvenance,
    build_provenance,
    classify_provenance,
)


class TestClassifyProvenance:
    def test_default(self):
        assert (
            classify_provenance("a", base_rules={"a"}, global_rules=set())
            == RuleProvenance.DEFAULT
        )

    def test_user(self):
        assert (
            classify_provenance("b", base_rules=set(), global_rules={"b"}) == RuleProvenance.USER
        )

    def test_project(self):
        assert (
            classify_provenance("c", base_rules=set(), global_rules=set())
            == RuleProvenance.PROJECT
        )


class TestBuildProvenance:
    def _settings(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": ["Bash(ls:*)", "Bash(local:*)", "User(x)", 123],
                        "deny": ["Bash(sudo:*)", "Bash(localdeny:*)"],
                    }
                }
            )
        )
        return path

    def test_tags_each_origin(self, tmp_path: Path):
        config = {"base_permissions": ["Bash(ls:*)"], "base_denies": ["Bash(sudo:*)"]}
        result = build_provenance(
            settings_path=self._settings(tmp_path), config=config, global_rules={"User(x)"}
        )
        assert isinstance(result, SuccessResult)
        counts = result.value["counts"]
        assert counts["default"] == 2  # Bash(ls:*) allow + Bash(sudo:*) deny
        assert counts["user"] == 1  # User(x)
        assert counts["project"] == 2  # Bash(local:*) + Bash(localdeny:*)
        # The non-string allow entry (123) is dropped, not classified.
        assert all(isinstance(entry["rule"], str) for entry in result.value["rules"])

    def test_reads_global_when_not_injected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "dev10x.skills.permission.provenance._load_global_allow_rules",
            lambda: ({"User(x)"}, []),
        )
        result = build_provenance(
            settings_path=self._settings(tmp_path),
            config={"base_permissions": [], "base_denies": []},
        )
        assert isinstance(result, SuccessResult)
        assert result.value["counts"]["user"] == 1

    def test_missing_file(self, tmp_path: Path):
        result = build_provenance(settings_path=tmp_path / "absent.json", config={})
        assert isinstance(result, ErrorResult)
        assert "not found" in result.error

    def test_bad_json(self, tmp_path: Path):
        path = tmp_path / "settings.local.json"
        path.write_text("{not json")
        result = build_provenance(settings_path=path, config={})
        assert isinstance(result, ErrorResult)
        assert "cannot read" in result.error
