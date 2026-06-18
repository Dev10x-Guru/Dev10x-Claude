"""Tests for the sensitivity-exception catalog loader (GH-604).

The loader reads ~/.config/Dev10x/sensitivity-exceptions.yaml into
domain SensitivityException value objects and fails open (empty/partial
list, logged warning) on a missing file, malformed YAML, or an invalid
entry — a broken catalog must never break the bash hook.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.sensitivity import ExceptionEffect, SensitivityLabel
from dev10x.validators.sensitivity_exceptions import load_sensitivity_exceptions


@pytest.fixture()
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEV10X_CONFIG_HOME", str(tmp_path))
    Dev10xConfigDir.reset_cache()
    yield tmp_path
    Dev10xConfigDir.reset_cache()


def _write(config_home: Path, body: str) -> None:
    (config_home / "sensitivity-exceptions.yaml").write_text(body, encoding="utf-8")


class TestMissingOrEmpty:
    def test_missing_file_returns_empty(self, config_home: Path) -> None:
        assert load_sensitivity_exceptions() == []

    def test_empty_exceptions_key_returns_empty(self, config_home: Path) -> None:
        _write(config_home, "exceptions: []\n")
        assert load_sensitivity_exceptions() == []

    def test_absent_exceptions_key_returns_empty(self, config_home: Path) -> None:
        _write(config_home, "other: 1\n")
        assert load_sensitivity_exceptions() == []


class TestValidEntries:
    def test_full_entry_parsed(self, config_home: Path) -> None:
        _write(
            config_home,
            """
exceptions:
  - description: bastion port probe
    label: infra
    shape: '\\bnc\\b.*-[zv]+'
    target: 'bastion\\.example\\.internal'
    effect: allow
""",
        )
        exceptions = load_sensitivity_exceptions()
        assert len(exceptions) == 1
        exc = exceptions[0]
        assert exc.description == "bastion port probe"
        assert exc.label is SensitivityLabel.INFRA
        assert exc.effect is ExceptionEffect.ALLOW
        assert exc.shape is not None and exc.shape.search("nc -zv host 5432")
        assert exc.target is not None and exc.target.search("bastion.example.internal")

    def test_effect_defaults_to_allow(self, config_home: Path) -> None:
        _write(config_home, "exceptions:\n  - shape: '\\bnc\\b'\n")
        assert load_sensitivity_exceptions()[0].effect is ExceptionEffect.ALLOW

    def test_explicit_ask_effect(self, config_home: Path) -> None:
        _write(config_home, "exceptions:\n  - shape: '\\bnc\\b'\n    effect: ask\n")
        assert load_sensitivity_exceptions()[0].effect is ExceptionEffect.ASK

    def test_target_pattern_is_case_insensitive(self, config_home: Path) -> None:
        _write(config_home, "exceptions:\n  - target: 'Bastion'\n")
        exc = load_sensitivity_exceptions()[0]
        assert exc.target is not None and exc.target.search("ssh bastion")


class TestDefensiveParsing:
    def test_malformed_yaml_returns_empty(self, config_home: Path) -> None:
        _write(config_home, "exceptions: [unclosed\n")
        assert load_sensitivity_exceptions() == []

    def test_non_mapping_root_returns_empty(self, config_home: Path) -> None:
        _write(config_home, "- just\n- a\n- list\n")
        assert load_sensitivity_exceptions() == []

    def test_exceptions_not_a_list_returns_empty(self, config_home: Path) -> None:
        _write(config_home, "exceptions: not-a-list\n")
        assert load_sensitivity_exceptions() == []

    def test_invalid_effect_skips_entry(self, config_home: Path) -> None:
        _write(
            config_home,
            "exceptions:\n  - shape: '\\bnc\\b'\n    effect: bogus\n"
            "  - shape: '\\bdig\\b'\n    effect: allow\n",
        )
        exceptions = load_sensitivity_exceptions()
        assert len(exceptions) == 1
        assert exceptions[0].shape is not None and exceptions[0].shape.search("dig host")

    def test_invalid_label_skips_entry(self, config_home: Path) -> None:
        _write(config_home, "exceptions:\n  - label: nonsense\n")
        assert load_sensitivity_exceptions() == []

    def test_matcherless_entry_skipped(self, config_home: Path) -> None:
        _write(
            config_home, "exceptions:\n  - effect: allow\n    description: blesses everything\n"
        )
        assert load_sensitivity_exceptions() == []

    def test_bad_regex_skips_entry(self, config_home: Path) -> None:
        _write(config_home, "exceptions:\n  - shape: '([unclosed'\n")
        assert load_sensitivity_exceptions() == []

    def test_non_mapping_entry_skipped_others_kept(self, config_home: Path) -> None:
        _write(config_home, "exceptions:\n  - just-a-string\n  - shape: '\\bnc\\b'\n")
        exceptions = load_sensitivity_exceptions()
        assert len(exceptions) == 1
