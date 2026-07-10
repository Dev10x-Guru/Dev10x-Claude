"""`dev10x session` — manage the project's session config.

The `seed` subcommand exists so a shell-only `post-checkout` git hook
can guarantee a new checkout is ready without invoking a Claude skill (a
git hook cannot). Since ADR-0018 durable prefs live in a single global
`~/.config/Dev10x/friction.yaml` (keyed by project dir-path globs), and
the ephemeral per-repo `session.yaml`/`config.yaml` are retired — nothing
under a repo's `.claude/` is written on the hot path, so Claude Code's
self-settings gate never fires (GH-812). So `seed` now only:

- ensures the global `friction.yaml` exists (a starter with a `defaults:`
  block; hand-authored thereafter), and
- ensures a self-ignoring `.gitignore` under `.claude/Dev10x/` so the
  MCP-written auto-advance doubt-sink stays out of `git status`.

Both writes are idempotent (`O_EXCL`): an existing file is left
untouched, so the hook may call `seed` unconditionally.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import FrictionYamlDocument


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
    help="Friction level for a fresh global friction.yaml (defaults to "
    "guided). Ignored when friction.yaml already exists.",
)
def seed(*, project_path: Path | None, friction_level: str | None) -> None:
    """Ensure the global friction.yaml + the .claude/Dev10x/ .gitignore exist.

    Idempotent (``O_EXCL``): present files are preserved, so a post-checkout
    hook may call ``seed`` unconditionally. Since ADR-0018 durable prefs are
    global (``~/.config/Dev10x/friction.yaml``) and the per-repo
    ``session.yaml``/``config.yaml`` are retired, seed no longer writes
    anything durable under the repo's ``.claude/``.
    """
    project_root = (project_path or Path.cwd()).resolve()

    # 1. Ensure the global friction.yaml exists (starter defaults block).
    friction_path = Dev10xConfigDir.friction_yaml()
    if _create_if_absent(
        target=friction_path,
        content=FrictionYamlDocument.render_starter(
            friction_level=(friction_level or "guided").lower(),
        ),
    ):
        click.echo(f"seeded {friction_path}")
    else:
        click.echo(f"friction.yaml already present at {friction_path}")

    # 2. Self-ignoring .gitignore keeps the MCP-written auto-advance doubt-sink
    # (and any other runtime artifact) under .claude/Dev10x/ out of git status,
    # so the clean-tree gates in verify_pr_state, gh-pr-merge Check 5,
    # verify-acc-dod, and create_pr never trip on it. A single "*" ignores
    # everything in the directory including the .gitignore itself (GH-809).
    gitignore = project_root / ".claude" / "Dev10x" / ".gitignore"
    if _create_if_absent(target=gitignore, content="*\n"):
        click.echo(f"seeded {gitignore}")
    else:
        click.echo(f".gitignore already present at {gitignore}")
