"""GH-1261: fold one IDE's rules, and nothing when there is no IDE."""

from __future__ import annotations

import pytest

from dev10x.domain.common.ide_choice import (
    IDE_ALLOW_KEY,
    IDE_DENY_KEY,
    Ide,
    apply_ide_selection,
    ide_inventory,
    parse_ide,
)

CATALOG = {
    "base_permissions": ["Bash(existing:*)"],
    "base_denies": ["Bash(sudo:*)"],
    IDE_ALLOW_KEY: {"pycharm": ["mcp__pycharm__read_file", "mcp__pycharm__rename_refactoring"]},
    IDE_DENY_KEY: {"pycharm": ["mcp__pycharm__execute_terminal_command"]},
}


class TestParseIde:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("pycharm", Ide.PYCHARM), ("PyCharm", Ide.PYCHARM), (" none ", Ide.NONE)],
    )
    def test_a_known_name_resolves(self, value: str, expected: Ide):
        assert parse_ide(value) is expected

    @pytest.mark.parametrize("value", ["vscode", "", None, 7, ["pycharm"]])
    def test_anything_else_is_not_configured(self, value: object):
        # A typo degrades to the caller's default rather than raising
        # inside a seeding run.
        assert parse_ide(value) is None

    def test_the_default_is_no_ide(self):
        # Unlike a tracker, most checkouts have no IDE server at all.
        assert Ide.default() is Ide.NONE


class TestApplyIdeSelection:
    def test_the_selected_ide_rules_are_folded_in(self):
        merged = apply_ide_selection(config=CATALOG, ide=Ide.PYCHARM)

        assert "mcp__pycharm__read_file" in merged["base_permissions"]
        assert "mcp__pycharm__execute_terminal_command" in merged["base_denies"]

    def test_existing_flat_rules_survive(self):
        merged = apply_ide_selection(config=CATALOG, ide=Ide.PYCHARM)

        assert "Bash(existing:*)" in merged["base_permissions"]
        assert "Bash(sudo:*)" in merged["base_denies"]

    def test_no_ide_folds_nothing(self):
        # The whole point of `none` being the default: a user without an
        # IDE server collects no inert rules.
        merged = apply_ide_selection(config=CATALOG, ide=Ide.NONE)

        assert merged["base_permissions"] == ["Bash(existing:*)"]
        assert merged["base_denies"] == ["Bash(sudo:*)"]

    def test_applying_twice_changes_nothing_further(self):
        once = apply_ide_selection(config=CATALOG, ide=Ide.PYCHARM)
        twice = apply_ide_selection(config=once, ide=Ide.PYCHARM)

        assert twice["base_permissions"] == once["base_permissions"]
        assert twice["base_denies"] == once["base_denies"]

    def test_the_input_catalog_is_not_mutated(self):
        # Seeding reads the shipped catalog from a cached loader, so a
        # mutation would leak the first run's IDE into every later one.
        apply_ide_selection(config=CATALOG, ide=Ide.PYCHARM)

        assert CATALOG["base_permissions"] == ["Bash(existing:*)"]

    def test_a_catalog_without_the_block_is_handled(self):
        merged = apply_ide_selection(config={"base_permissions": []}, ide=Ide.PYCHARM)

        assert merged["base_permissions"] == []


class TestIdeInventory:
    def test_every_ide_is_reported(self):
        inventory = ide_inventory(config=CATALOG)

        assert set(inventory) == set(Ide)

    def test_an_ide_with_no_block_is_falsy(self):
        assert not ide_inventory(config=CATALOG)[Ide.NONE]
