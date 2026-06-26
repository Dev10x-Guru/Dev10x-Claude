"""`dev10x session` — manage the project's session config.

The `seed` subcommand exists so a shell-only `post-checkout` git hook
can guarantee a new worktree has a `.claude/Dev10x/session.yaml`
without invoking a Claude skill (a git hook cannot). It is idempotent:
an existing file (e.g. one the hook copied from the source worktree)
is left untouched, so the hook may call it unconditionally.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from dev10x.domain.documents.session_yaml import SessionYamlDocument


@click.group()
def session() -> None:
    """Manage the project's .claude/Dev10x/session.yaml config."""


@session.command()
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project root (defaults to the current directory).",
)
@click.option(
    "--friction-level",
    type=click.Choice(["strict", "guided", "adaptive"], case_sensitive=False),
    default="guided",
    help="Friction level to seed when the file is absent.",
)
def seed(*, project_path: Path | None, friction_level: str) -> None:
    """Write a default session.yaml only when one does not already exist.

    Idempotent (``O_EXCL``): a present session.yaml is preserved so a
    post-checkout hook can copy session state from the source worktree
    first and fall back to this seed only when the source had none.
    """
    project_root = (project_path or Path.cwd()).resolve()
    target = SessionYamlDocument(toplevel=str(project_root)).path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        click.echo(f"session.yaml already present at {target}")
        return
    try:
        os.write(fd, SessionYamlDocument.render(friction_level=friction_level.lower()).encode())
    finally:
        os.close(fd)
    click.echo(f"seeded {target}")
