"""Guards for the Click LazyGroup CLI (GH-249 H10).

The lazy-loading CLI defers subcommand imports for startup speed
(see `.claude/rules/performance.md`). These tests pin the registered
subcommand set so a subcommand cannot silently fall out of the
`lazy_subcommands` map, and verify every declared import path resolves
to a real Click command.
"""

from __future__ import annotations

import click
import pytest

from dev10x.cli import cli

EXPECTED_SUBCOMMANDS = {
    "config",
    "github",
    "github-app",
    "hook",
    "init",
    "permission",
    "platform",
    "playbook",
    "session",
    "validate",
    "skill",
    "usage",
}


def test_all_subcommands_registered_lazily() -> None:
    assert set(cli._lazy_subcommands) == EXPECTED_SUBCOMMANDS


def test_list_commands_includes_every_lazy_subcommand() -> None:
    ctx = click.Context(cli)
    listed = cli.list_commands(ctx)
    assert EXPECTED_SUBCOMMANDS.issubset(set(listed))


@pytest.mark.parametrize("name", sorted(EXPECTED_SUBCOMMANDS))
def test_lazy_subcommand_loads(name: str) -> None:
    ctx = click.Context(cli)
    command = cli.get_command(ctx, name)
    assert isinstance(command, click.BaseCommand)
