"""Tests for dev10x.cli — Click CLI entry point and lazy loading."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from dev10x.cli import LazyGroup, cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestCli:
    def test_help_output(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "hook" in result.output
        assert "validate" in result.output
        assert "skill" in result.output

    def test_version_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert "version" in result.output.lower()

    def test_unknown_command(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["nonexistent"])

        assert result.exit_code != 0


class TestLazyGroup:
    def test_list_commands_includes_lazy(self) -> None:
        group = LazyGroup(
            name="test",
            lazy_subcommands={"alpha": "os.path.join", "beta": "os.path.exists"},
        )
        ctx = click.Context(group)

        commands = group.list_commands(ctx=ctx)

        assert "alpha" in commands
        assert "beta" in commands

    def test_list_commands_sorted(self) -> None:
        group = LazyGroup(
            name="test",
            lazy_subcommands={"zebra": "os.path.join", "apple": "os.path.exists"},
        )
        ctx = click.Context(group)

        lazy_commands = group.list_commands(ctx=ctx)

        assert lazy_commands.index("apple") < lazy_commands.index("zebra")

    def test_get_command_loads_lazy(self) -> None:
        @click.command()
        def dummy_cmd() -> None:
            pass

        group = LazyGroup(
            name="test",
            lazy_subcommands={"dummy": f"{__name__}.dummy_cmd"},
        )
        group._lazy_subcommands["dummy"] = f"{dummy_cmd.__module__}.dummy_cmd"

        ctx = click.Context(group)
        group.get_command(ctx=ctx, cmd_name="hook")

        # hook is a real lazy subcommand in cli
        result = cli.get_command(ctx=click.Context(cli), cmd_name="hook")
        assert result is not None
        assert isinstance(result, click.BaseCommand)

    def test_get_command_returns_none_for_unknown(self) -> None:
        group = LazyGroup(name="test", lazy_subcommands={})
        ctx = click.Context(group)

        result = group.get_command(ctx=ctx, cmd_name="nonexistent")

        assert result is None
