"""`dev10x init` — guided onboarding for new users.

Creates a starter `.claude/Dev10x/` config tree in the current project
and prints a quick-start card covering the top 5 workflows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import FrictionYamlDocument

QUICK_START_WORKFLOWS = [
    (
        "git-commit",
        "/Dev10x:git-commit",
        "JTBD-style commit messages with gitmoji + ticket ID",
    ),
    (
        "pr-create",
        "/Dev10x:gh-pr-create",
        "Draft PR with Job Story body and Fixes: link",
    ),
    (
        "review",
        "/Dev10x:review",
        "Self-review your branch before requesting a human reviewer",
    ),
    (
        "testing",
        "/test",
        "Run pytest with coverage enforcement",
    ),
    (
        "architecture",
        "/Dev10x:adr",
        "Author Architecture Decision Records with diagrams",
    ),
]

STARTER_WORK_ON_PLAYBOOK = """# Starter work-on playbook for this project.
#
# Customize with /Dev10x:playbook edit work-on <play>
# See skills/playbook/references/playbook.yaml for the full schema.

# active_modes controls per-step behavior adaptations. Uncomment any
# that apply to this project:
#
# active_modes:
#   - solo-maintainer   # skip reviewer assignment + Slack notifications
#   - open-source       # prefer issue templates and public-safe language

overrides: []
"""


def _write_if_missing(path: Path, content: str) -> bool:
    # GH-562: claim the file atomically with O_EXCL instead of a
    # check-then-write. Two concurrent `dev10x init` runs (CI matrix)
    # otherwise both see the file absent and the second clobbers any
    # interactive customization the first made.
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _display_path(path: Path, *, project_root: Path) -> str:
    """Render ``path`` relative to the project when possible, else absolute.

    The global ``friction.yaml`` lives outside the project (ADR-0018), so a
    naive ``relative_to`` would raise — fall back to the absolute path.
    """
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _project_playbook_path(project_root: Path) -> Path:
    return project_root / ".claude" / "Dev10x" / "playbooks" / "work-on.yaml"


def _seed_project(
    project_root: Path,
    *,
    friction_level: str = "guided",
    active_modes: list[str] | None = None,
) -> list[Path]:
    """Create starter config files. Returns list of paths written.

    Durable prefs live in the global ``~/.config/Dev10x/friction.yaml``
    (ADR-0018); the only per-project starter is the work-on playbook.
    """
    written: list[Path] = []
    targets = [
        (
            Dev10xConfigDir.friction_yaml(),
            FrictionYamlDocument.render_starter(
                friction_level=friction_level, active_modes=active_modes
            ),
        ),
        (_project_playbook_path(project_root), STARTER_WORK_ON_PLAYBOOK),
    ]
    for path, content in targets:
        if _write_if_missing(path, content):
            written.append(path)

    return written


def _print_card(*, project_root: Path) -> None:
    click.echo("")
    click.echo("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    click.echo(" Dev10x — Next 5 commands")
    click.echo("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for i, (workflow, command, description) in enumerate(QUICK_START_WORKFLOWS, start=1):
        click.echo(f" {i}. {command:<28} {workflow}")
        click.echo(f"    {description}")
    click.echo("")
    click.echo(f" Config: {project_root}/.claude/Dev10x/")
    click.echo(" Customize: /Dev10x:playbook edit work-on <play>")
    click.echo(" Discovery: /Dev10x:onboarding")
    click.echo("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    click.echo("")


@click.command()
@click.option(
    "--setup",
    is_flag=True,
    help="Force interactive setup even when config already exists.",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Skip interactive prompts; write starter config and print card only.",
)
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project root (defaults to current directory).",
)
def init(*, setup: bool, non_interactive: bool, project_path: Path | None) -> None:
    """Create a starter .claude/Dev10x/ config and print the quick-start card."""
    project_root = (project_path or Path.cwd()).resolve()

    if not project_root.is_dir():
        click.echo(f"Project path does not exist: {project_root}", err=True)
        sys.exit(1)

    existing = _project_playbook_path(project_root).exists()
    if existing and not setup:
        click.echo(f"Dev10x config already present at {project_root}/.claude/Dev10x/")
        _print_card(project_root=project_root)
        return

    if non_interactive:
        written = _seed_project(project_root)
        for path in written:
            click.echo(f"  + {_display_path(path, project_root=project_root)}")
        _print_card(project_root=project_root)
        return

    click.echo("")
    click.echo(f"Setting up Dev10x in {project_root}")
    click.echo("")

    friction_level = click.prompt(
        "Friction level",
        type=click.Choice(["strict", "guided", "adaptive"], case_sensitive=False),
        default="guided",
    )
    solo = click.confirm(
        "Solo maintainer mode? (skips reviewer assignment and Slack notifications)",
        default=False,
    )

    modes = ["solo-maintainer"] if solo else []
    # Durable prefs land in the global friction.yaml (ADR-0018); the starter
    # is written only when absent so re-running init never clobbers a
    # hand-authored global file. The per-project playbook is always ensured.
    for path in _seed_project(
        project_root, friction_level=friction_level.lower(), active_modes=modes
    ):
        click.echo(f"  + {_display_path(path, project_root=project_root)}")

    _print_card(project_root=project_root)
