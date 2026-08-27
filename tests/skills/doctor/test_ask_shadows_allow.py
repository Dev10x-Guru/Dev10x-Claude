"""Tests for the ask-shadows-allow doctor strategy (GH-1067)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.skills.doctor.strategies import ask_shadows_allow
from dev10x.skills.doctor.strategy import Context


def _settings(tmp_path: Path, **buckets: list[str]) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(json.dumps({"permissions": buckets}), encoding="utf-8")
    return path


def _detect(path: Path) -> list:
    return ask_shadows_allow.detect(Context(settings_paths=(path,)))


class TestDetect:
    def test_narrow_ask_over_broad_allow_is_reported(self, tmp_path: Path) -> None:
        """The GH-1007 E10 shape: ask on -D shadows the branch family."""
        path = _settings(
            tmp_path,
            allow=["Bash(git branch:*)", "Bash(git branch -d:*)"],
            ask=["Bash(git branch -D:*)"],
        )
        (finding,) = _detect(path)
        assert finding.strategy_id == "ask-shadows-allow"
        assert finding.severity == "drift"
        assert "Bash(git branch -D:*)" in finding.evidence
        assert "Bash(git branch:*)" in finding.evidence

    def test_deny_bucket_is_checked_too(self, tmp_path: Path) -> None:
        path = _settings(
            tmp_path,
            allow=["Bash(git stash:*)"],
            deny=["Bash(git stash clear:*)"],
        )
        (finding,) = _detect(path)
        assert finding.data.gate_bucket == "deny"

    def test_exact_duplicate_across_buckets_is_reported(self, tmp_path: Path) -> None:
        path = _settings(
            tmp_path,
            allow=["Bash(git stash drop:*)"],
            ask=["Bash(git stash drop:*)"],
        )
        assert len(_detect(path)) == 1

    def test_unrelated_gate_rule_is_not_reported(self, tmp_path: Path) -> None:
        path = _settings(
            tmp_path,
            allow=["Bash(git branch:*)"],
            ask=["Bash(rm -rf:*)"],
        )
        assert _detect(path) == []

    def test_gate_on_a_different_tool_is_not_reported(self, tmp_path: Path) -> None:
        path = _settings(
            tmp_path,
            allow=["Bash(git branch:*)"],
            ask=["Read(/etc/**)"],
        )
        assert _detect(path) == []

    def test_no_allow_list_yields_no_findings(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, ask=["Bash(git branch -D:*)"])
        assert _detect(path) == []

    def test_missing_file_yields_no_findings(self, tmp_path: Path) -> None:
        assert _detect(tmp_path / "absent.json") == []

    def test_malformed_json_yields_no_findings(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text("{not json", encoding="utf-8")
        assert _detect(path) == []

    def test_non_mapping_permissions_yields_no_findings(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": "nope"}), encoding="utf-8")
        assert _detect(path) == []

    def test_non_string_rules_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(
            json.dumps({"permissions": {"allow": ["Bash(git branch:*)", 7], "ask": [7]}}),
            encoding="utf-8",
        )
        assert _detect(path) == []

    def test_path_glob_allow_is_matched_by_representative_value(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, allow=["Read(/a/**)"], ask=["Read(/a/b/**)"])
        (finding,) = _detect(path)
        assert finding.data.shadowed_allow_rules == ("Read(/a/**)",)

    def test_exact_rule_without_a_wildcard_suffix_is_compared_verbatim(
        self,
        tmp_path: Path,
    ) -> None:
        """A gate rule carrying neither `:*` nor `**` still shadows its family."""
        path = _settings(tmp_path, allow=["Bash(git branch:*)"], ask=["Bash(git branch -D)"])
        (finding,) = _detect(path)
        assert finding.data.gate_rule == "Bash(git branch -D)"

    def test_empty_context_falls_back_to_home_settings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": ["Bash(git branch:*)"],
                        "ask": ["Bash(git branch -D:*)"],
                    }
                }
            ),
            encoding="utf-8",
        )
        assert len(ask_shadows_allow.detect(Context())) == 1


class TestRemediate:
    def test_remediation_names_the_settings_file_and_both_buckets(self, tmp_path: Path) -> None:
        path = _settings(
            tmp_path,
            allow=["Bash(git branch:*)"],
            ask=["Bash(git branch -D:*)"],
        )
        (finding,) = _detect(path)
        remediation = ask_shadows_allow.remediate(finding)
        assert remediation.kind == "edit_settings"
        assert remediation.target == str(path)
        assert remediation.action["bucket"] == "ask"
        assert remediation.action["rule"] == "Bash(git branch -D:*)"
        assert remediation.action["shadowed_allow_rules"] == ["Bash(git branch:*)"]
