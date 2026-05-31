"""Tests for the shared permission config loader (GH-246 H12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.permission.config import parse_config, resolve_config


class TestResolveConfig:
    def test_returns_first_existing_candidate(self, tmp_path: Path):
        first = tmp_path / "first.yaml"
        second = tmp_path / "second.yaml"
        first.write_text("a: 1")
        second.write_text("b: 2")
        assert resolve_config(candidates=[first, second]) == first

    def test_skips_missing_candidates(self, tmp_path: Path):
        missing = tmp_path / "missing.yaml"
        present = tmp_path / "present.yaml"
        present.write_text("a: 1")
        assert resolve_config(candidates=[missing, present]) == present

    def test_exits_with_generic_message_when_none_found(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            resolve_config(candidates=[tmp_path / "nope.yaml"])
        assert exc.value.code == 1
        assert capsys.readouterr().err.strip() == "ERROR: No config found."

    def test_exits_with_create_hint_when_provided(self, tmp_path, capsys):
        create = tmp_path / "make-me.yaml"
        plugin = tmp_path / "plugin.yaml"
        with pytest.raises(SystemExit) as exc:
            resolve_config(candidates=[create, plugin], create_path=create)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert str(create) in err
        assert str(plugin) in err


class TestParseConfig:
    def test_parses_yaml_into_dict(self, tmp_path: Path):
        config = tmp_path / "c.yaml"
        config.write_text("roots:\n  - /a\n  - /b\n")
        assert parse_config(config_path=config) == {"roots": ["/a", "/b"]}
