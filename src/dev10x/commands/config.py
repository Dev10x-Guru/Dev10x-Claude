"""CLI for Dev10x userspace config — migration helpers (GH-215)."""

from __future__ import annotations

import click

from dev10x.domain.dev10x_paths import (
    Dev10xConfigDir,
    migrate_all,
    stale_legacy_paths,
)


@click.group()
def config() -> None:
    """Manage Dev10x userspace configuration."""


@config.command(name="root")
def root() -> None:
    """Print the resolved Dev10x config root."""
    click.echo(Dev10xConfigDir.home())


@config.command(name="migrate")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show which legacy files would be copied without writing.",
)
def migrate(*, dry_run: bool) -> None:
    """Copy legacy ~/.claude/{memory/Dev10x,Dev10x}/ files to ~/.config/Dev10x/."""
    stale = stale_legacy_paths()
    if not stale:
        click.echo("No legacy Dev10x config files found.")
        return
    if dry_run:
        click.echo(f"Would migrate {len(stale)} legacy entr{'y' if len(stale) == 1 else 'ies'}:")
        for path in stale:
            click.echo(f"  - {path}")
        return
    migrated = migrate_all()
    if not migrated:
        click.echo("Nothing to migrate — destination already populated.")
        return
    click.echo(f"Migrated {len(migrated)} entr{'y' if len(migrated) == 1 else 'ies'}:")
    for path in migrated:
        click.echo(f"  - {path}")


@config.command(name="doctor")
def doctor() -> None:
    """Report legacy Dev10x config files that still need migration."""
    stale = stale_legacy_paths()
    if not stale:
        click.echo("Dev10x config: all files at canonical XDG location.")
        return
    click.echo(f"Found {len(stale)} legacy Dev10x config entr{'y' if len(stale) == 1 else 'ies'}:")
    for path in stale:
        click.echo(f"  - {path}")
    click.echo("\nRun `dev10x config migrate` to copy them to ~/.config/Dev10x/.")
