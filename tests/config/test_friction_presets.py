"""Tests for friction-preset hydration (ADR-0016 #752, Q2).

The drift-guard tests are load-bearing: they assert the shipped
``presets/friction/*.yaml`` stays byte-for-value identical to the
pure-domain default constants, so the "move to YAML" cannot silently
diverge from the resolver's fallback.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.config.friction_presets import (
    load_shipped_overlays,
    load_shipped_presets,
    load_user_presets,
)
from dev10x.domain.gate_policy import SHIPPED_OVERLAYS, SHIPPED_PRESETS


class TestDriftGuard:
    def test_shipped_presets_yaml_matches_domain_default(self) -> None:
        assert load_shipped_presets() == SHIPPED_PRESETS

    def test_shipped_overlays_yaml_matches_domain_default(self) -> None:
        assert load_shipped_overlays() == SHIPPED_OVERLAYS


class TestLoaderRoots:
    def test_missing_preset_dir_yields_empty(self, tmp_path: Path) -> None:
        assert load_shipped_presets(plugin_root=tmp_path) == {}
        assert load_shipped_overlays(plugin_root=tmp_path) == {}

    def test_loads_presets_from_explicit_root(self, tmp_path: Path) -> None:
        friction = tmp_path / "presets" / "friction"
        (friction / "overlays").mkdir(parents=True)
        (friction / "custom.yaml").write_text("merge: ask\n")
        (friction / "overlays" / "freeze.yaml").write_text("merge: ask\n")
        assert load_shipped_presets(plugin_root=tmp_path) == {"custom": {"merge": "ask"}}
        assert load_shipped_overlays(plugin_root=tmp_path) == {"freeze": {"merge": "ask"}}

    def test_overlays_do_not_leak_into_presets(self, tmp_path: Path) -> None:
        friction = tmp_path / "presets" / "friction"
        (friction / "overlays").mkdir(parents=True)
        (friction / "overlays" / "freeze.yaml").write_text("merge: ask\n")
        # glob("*.yaml") is non-recursive — overlays stay out of the preset set.
        assert load_shipped_presets(plugin_root=tmp_path) == {}


class TestUserPresets:
    def test_missing_user_file_yields_empty(self, tmp_path: Path) -> None:
        assert load_user_presets(home=tmp_path) == {}

    def test_loads_user_presets_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / ".config" / "Dev10x" / "friction-presets.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("presets:\n  team-afk:\n    merge: ask\n")
        assert load_user_presets(home=tmp_path) == {"team-afk": {"merge": "ask"}}

    def test_malformed_user_file_degrades(self, tmp_path: Path) -> None:
        path = tmp_path / ".config" / "Dev10x" / "friction-presets.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(":\n  - not: [valid")
        assert load_user_presets(home=tmp_path) == {}

    def test_missing_presets_key_degrades(self, tmp_path: Path) -> None:
        path = tmp_path / ".config" / "Dev10x" / "friction-presets.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("something_else: true\n")
        assert load_user_presets(home=tmp_path) == {}
