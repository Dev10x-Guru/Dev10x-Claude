"""CLI for Dev10x userspace config — migration helpers (GH-215)."""

from __future__ import annotations

import os

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


@config.command(name="migrate-schema")
@click.option(
    "--cwd",
    "cwd",
    default=None,
    help="Repo root whose legacy .claude/Dev10x/config.yaml is folded in.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Report the posture change per entry without writing.",
)
def migrate_schema(*, cwd: str | None, dry_run: bool) -> None:
    """Convert v1 durable configs to ADR-0022 schema v2 (GH-1166).

    Rewrites `gate_preset` / `friction_level` / `human_review` /
    `walk_away` into `supervisor_review` + `gate_overlays`. Idempotent —
    a run with nothing left to convert writes nothing.
    """
    from dev10x.domain.config_migration import migrate_configs

    report = migrate_configs(toplevel=cwd or os.getcwd(), dry_run=dry_run).value
    if not report["pending"]:
        click.echo("Dev10x config: already at schema v2 (ADR-0022).")
        return
    verb = "Would convert" if dry_run else "Converted"
    plural = "y" if report["pending"] == 1 else "ies"
    click.echo(f"{verb} {report['pending']} durable config entr{plural}:")
    for store, part in report.items():
        if not isinstance(part, dict):
            continue
        for entry in part.get("entries", ()):
            click.echo(f"  - [{store}] {entry['scope']}")
            click.echo(f"      supervisor_review: {entry['supervisor_review']}")
            if entry["dropped_preset"]:
                click.echo(f"      retired preset dropped: {entry['dropped_preset']}")
            if entry["added_overlays"]:
                click.echo(f"      overlays added: {', '.join(entry['added_overlays'])}")
            if entry["dropped_keys"]:
                click.echo(f"      keys dropped: {', '.join(entry['dropped_keys'])}")
    if dry_run:
        click.echo("\nRun `dev10x config migrate-schema` to apply.")


@config.command(name="doctor")
def doctor() -> None:
    """Report legacy Dev10x config files and v1 schema entries needing migration."""
    from dev10x.domain.config_migration import migrate_configs

    stale = stale_legacy_paths()
    if stale:
        found = len(stale)
        click.echo(f"Found {found} legacy Dev10x config entr{'y' if found == 1 else 'ies'}:")
        for path in stale:
            click.echo(f"  - {path}")
        click.echo("\nRun `dev10x config migrate` to copy them to ~/.config/Dev10x/.")
    else:
        click.echo("Dev10x config: all files at canonical XDG location.")

    # Schema-v1 residue is a separate axis from file *location* (GH-1166):
    # a config already at the XDG path can still name a retired preset,
    # which post-GH-1162 resolution cannot honour.
    pending = migrate_configs(toplevel=os.getcwd(), dry_run=True).value["pending"]
    if not pending:
        click.echo("Dev10x config: durable prefs are at schema v2 (ADR-0022).")
        return
    click.echo(f"\nFound {pending} durable config entr{'y' if pending == 1 else 'ies'} on v1.")
    click.echo("Run `dev10x config migrate-schema --dry-run` to preview the conversion.")
