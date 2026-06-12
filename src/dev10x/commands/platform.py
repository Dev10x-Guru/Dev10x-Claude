"""`dev10x platform` — register and list AI assistant platforms."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
def platform() -> None:
    """Manage Dev10x target platforms (Claude Code, Copilot CLI, Windsurf, …)."""


@platform.command(name="add")
@click.argument("name")
@click.option(
    "--config-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override the platform's default config directory.",
)
@click.option(
    "--playbook",
    "playbook_override",
    type=str,
    default=None,
    help="Playbook file to prefer for this platform (relative to config dir).",
)
def add(
    *,
    name: str,
    config_dir: Path | None,
    playbook_override: str | None,
) -> None:
    """Register a platform so skills can target it without path editing."""
    from dev10x.platform import PlatformRepository, known_platforms

    catalog = known_platforms()
    if name not in catalog:
        click.echo(
            f"Unknown platform '{name}'. Known: {', '.join(sorted(catalog))}",
            err=True,
        )
        sys.exit(1)

    registry = PlatformRepository()
    cfg = registry.add(
        name=name,
        config_dir=config_dir.expanduser().resolve() if config_dir else None,
        playbook_override=playbook_override,
    )

    click.echo(f"✓ Registered {cfg.display_name} ({cfg.name})")
    click.echo(f"  config:   {cfg.config_dir}")
    click.echo(f"  plugins:  {cfg.plugins_dir}")
    click.echo(f"  settings: {cfg.settings_file}")
    if cfg.playbook_override:
        click.echo(f"  playbook: {cfg.playbook_override}")


@platform.command(name="list")
def list_platforms() -> None:
    """Show every registered platform with its configured paths."""
    from dev10x.platform import PlatformRepository

    registry = PlatformRepository()
    entries = registry.list()

    if not entries:
        click.echo("No platforms registered. Run `dev10x platform add <name>` first.")
        return

    for cfg in entries:
        click.echo(f"{cfg.display_name}  ({cfg.name})")
        click.echo(f"  config:   {cfg.config_dir}")
        click.echo(f"  plugins:  {cfg.plugins_dir}")
        if cfg.playbook_override:
            click.echo(f"  playbook: {cfg.playbook_override}")
        click.echo("")


@platform.command(name="remove")
@click.argument("name")
def remove(*, name: str) -> None:
    """Unregister a platform from the local registry."""
    from dev10x.platform import PlatformRepository

    registry = PlatformRepository()
    if registry.remove(name):
        click.echo(f"✓ Removed {name}")
    else:
        click.echo(f"No registration found for {name}", err=True)
        sys.exit(1)


@platform.command(name="known")
def known() -> None:
    """Print the built-in catalog of supported platforms."""
    from dev10x.platform import known_platforms

    for name, cfg in sorted(known_platforms().items()):
        click.echo(f"{name:<14} {cfg.display_name}")
