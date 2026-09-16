"""`dev10x orchestration` — checks an orchestrator runs on its children.

Today that is one check: has a finished agent left work uncommitted in a
worktree that is about to be reclaimed (GH-1363)?
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from dev10x.skills.orchestration.subagent_protocol import SubagentStatus


@click.group()
def orchestration() -> None:
    """Inspect background agents before their worktrees are reclaimed."""


@orchestration.command(name="stranded-work")
@click.argument("worktree", type=click.Path(path_type=Path))
@click.option(
    "--status",
    type=click.Choice([member.value for member in SubagentStatus]),
    default=SubagentStatus.DONE.value,
    show_default=True,
    help="The status token the agent reported.",
)
def stranded_work_command(*, worktree: Path, status: str) -> None:
    """Report uncommitted work in an agent's worktree.

    Exits 1 when a resume is required, so a caller can branch on the exit
    code; the verdict JSON goes to stdout either way.
    """
    from dev10x.skills.orchestration.stranded_work import inspect_worktree, resume_prompt

    verdict = inspect_worktree(worktree=worktree, status=SubagentStatus(status))
    payload = verdict.to_dict()
    payload["resume_prompt"] = resume_prompt(verdict=verdict)
    click.echo(json.dumps(payload, indent=2))

    if verdict.resume_required:
        raise SystemExit(1)
