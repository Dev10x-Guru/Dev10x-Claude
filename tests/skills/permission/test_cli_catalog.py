"""CLI ↔ permission-catalog drift check (GH-595).

The live-catalog test is the CI drift gate: it enumerates the real
``dev10x`` Click tree and fails when an agent-facing subcommand lacks a
covering ``dev10x-cli`` allow-rule. Running under the standard pytest CI
job means a new subcommand cannot merge without its catalog entry.
"""

from __future__ import annotations

from pathlib import Path

import click
import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.cli import cli
from dev10x.skills.permission.cli_catalog import (
    catalog_rule_paths,
    enumerate_leaf_commands,
    find_uncovered_commands,
)

CATALOG = Path(permission_pkg.__file__).parent / "baseline-permissions.yaml"


def _write_catalog(path: Path, rules: list[str]) -> Path:
    path.write_text(yaml.safe_dump({"groups": {"dev10x-cli": {"rules": rules}}}))
    return path


def _build_cli() -> click.Group:
    @click.group()
    def root() -> None: ...

    @root.group()
    def permission() -> None: ...

    @permission.command()
    def clean() -> None: ...

    @permission.command(name="brand-new")
    def brand_new() -> None: ...  # synthetic uncovered subcommand

    @root.group()
    def hook() -> None: ...

    @hook.command(name="validate-bash")
    def validate_bash() -> None: ...  # internal — excluded

    return root


class TestEnumerateLeafCommands:
    def test_recurses_to_leaves(self) -> None:
        leaves = enumerate_leaf_commands(_build_cli())
        assert ("permission", "clean") in leaves
        assert ("permission", "brand-new") in leaves
        assert ("hook", "validate-bash") in leaves


class TestCatalogRulePaths:
    def test_parses_uvx_dev10x_rules(self, tmp_path: Path) -> None:
        catalog = _write_catalog(
            tmp_path / "c.yaml",
            [
                "Bash(uvx dev10x permission clean:*)",
                "Bash(uvx dev10x config:*)",
                "Bash(git log:*)",  # non-dev10x rule ignored
            ],
        )
        assert catalog_rule_paths(catalog) == [("permission", "clean"), ("config",)]


class TestFindUncoveredCommands:
    def test_flags_uncovered_subcommand(self, tmp_path: Path) -> None:
        catalog = _write_catalog(tmp_path / "c.yaml", ["Bash(uvx dev10x permission clean:*)"])
        uncovered = find_uncovered_commands(cli_group=_build_cli(), catalog_path=catalog)
        assert uncovered == ["uvx dev10x permission brand-new"]

    def test_group_prefix_covers_leaves(self, tmp_path: Path) -> None:
        catalog = _write_catalog(
            tmp_path / "c.yaml",
            ["Bash(uvx dev10x permission:*)"],  # group wildcard covers all leaves
        )
        uncovered = find_uncovered_commands(cli_group=_build_cli(), catalog_path=catalog)
        assert uncovered == []

    def test_internal_groups_excluded(self, tmp_path: Path) -> None:
        # `hook` is internal — never needs a catalog rule.
        catalog = _write_catalog(
            tmp_path / "c.yaml",
            [
                "Bash(uvx dev10x permission clean:*)",
                "Bash(uvx dev10x permission brand-new:*)",
            ],
        )
        uncovered = find_uncovered_commands(cli_group=_build_cli(), catalog_path=catalog)
        assert uncovered == []


class TestLiveCatalogHasNoDrift:
    """CI gate: the shipped catalog must cover every agent-facing command."""

    def test_no_uncovered_commands(self) -> None:
        uncovered = find_uncovered_commands(cli_group=cli, catalog_path=CATALOG)
        assert uncovered == [], (
            "These dev10x subcommands lack a dev10x-cli allow-rule in "
            f"baseline-permissions.yaml: {uncovered}"
        )

    def test_skill_notify_is_covered(self) -> None:
        # GH-595 regression: the missing subcommand that prompted in-session.
        assert "uvx dev10x skill notify" not in find_uncovered_commands(
            cli_group=cli, catalog_path=CATALOG
        )
