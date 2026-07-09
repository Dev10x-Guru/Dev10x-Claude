"""`dev10x session` — manage the project's session config.

The `seed` subcommand exists so a shell-only `post-checkout` git hook
can guarantee a new worktree has its Dev10x config without invoking a
Claude skill (a git hook cannot). Since GH-774 the config is split:

- `config.yaml` — durable prefs (friction_level, active_modes). The hook
  copies this from the source worktree; seed provisions a default only
  when the source had none (e.g. a brand-new project).
- `session.yaml` — ephemeral per-worktree state; seeded fresh, never
  copied.

Both writes are idempotent (`O_EXCL`): an existing file is left
untouched, so the hook may call `seed` unconditionally.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from dev10x.domain.documents.session_yaml import ConfigYamlDocument, SessionYamlDocument


def _create_if_absent(*, target: Path, content: str) -> bool:
    """Atomically create ``target`` with ``content``; return whether written.

    Idempotent via ``O_EXCL`` — a present file is preserved so the hook may
    copy config from the source worktree first and fall back to this seed
    only when the source had none.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    return True


@click.group()
def session() -> None:
    """Manage the project's .claude/Dev10x/ session config."""


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
    default=None,
    help="Friction level for a fresh config.yaml. Omit to migrate a "
    "pre-split session.yaml's level (else defaults to guided).",
)
def seed(*, project_path: Path | None, friction_level: str | None) -> None:
    """Provision the durable config.yaml and ephemeral session.yaml.

    Idempotent (``O_EXCL``): a present file is preserved so a post-checkout
    hook can copy the durable config from the source worktree first and fall
    back to this seed only when the source had none (GH-774).

    Migration (GH-774): when config.yaml is absent but a pre-split
    session.yaml still carries the durable keys, seed lifts the effective
    ``friction_level`` / ``active_modes`` into config.yaml rather than
    overwriting them with defaults — so migrating a repo never silently
    downgrades an existing ``adaptive`` setting. An explicit
    ``--friction-level`` overrides the migrated level.
    """
    project_root = (project_path or Path.cwd()).resolve()
    config = ConfigYamlDocument(toplevel=str(project_root))
    session_doc = SessionYamlDocument(toplevel=str(project_root))

    # Read the EXPLICIT durable prefs BEFORE writing config.yaml — the
    # facade falls back to a pre-split session.yaml (the migration source)
    # and applies no defaulting, so an unset level falls back to "guided"
    # rather than to FrictionLevel.default().
    durable = session_doc.durable_prefs()
    existing_modes = durable.get("active_modes")
    # Carry a pre-existing overlay allow-list (GH-805) forward so a re-seed or
    # a pre-split→config.yaml migration never silently drops the repo-character
    # guard. Absent stays absent (permissive) — render omits the key entirely.
    existing_allowed = durable.get("allowed_overlays")
    seed_level = (friction_level or durable.get("friction_level") or "guided").lower()
    if _create_if_absent(
        target=config.path,
        content=ConfigYamlDocument.render(
            friction_level=seed_level,
            active_modes=existing_modes if isinstance(existing_modes, list) else None,
            allowed_overlays=existing_allowed if isinstance(existing_allowed, list) else None,
        ),
    ):
        click.echo(f"seeded {config.path}")
    else:
        click.echo(f"config.yaml already present at {config.path}")

    if _create_if_absent(target=session_doc.path, content=SessionYamlDocument.render_ephemeral()):
        click.echo(f"seeded {session_doc.path}")
    else:
        click.echo(f"session.yaml already present at {session_doc.path}")

    # GH-809: a self-ignoring .gitignore keeps every runtime artifact under
    # .claude/Dev10x/ (session.yaml, auto-advance-records.md, plan-sync state)
    # out of git status, so the clean-tree gates in verify_pr_state,
    # gh-pr-merge Check 5, verify-acc-dod, and create_pr never trip on session
    # state. A single "*" ignores everything in the directory including the
    # .gitignore itself, so no per-project .gitignore edit is needed.
    gitignore = config.path.parent / ".gitignore"
    if _create_if_absent(target=gitignore, content="*\n"):
        click.echo(f"seeded {gitignore}")
    else:
        click.echo(f".gitignore already present at {gitignore}")
