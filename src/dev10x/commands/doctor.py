"""``dev10x doctor`` — non-interactive plugin-doctor sweep (GH-1321).

The entry point owns stdout and the exit code; every decision lives in
:mod:`dev10x.skills.doctor.runner`, per
``.claude/rules/script-domain-boundaries.md``. Output is JSON on stdout
in both directions — a verdict and an ``{"error": ...}`` blob alike — so
a CI consumer parses one channel and never sees empty stdout on failure,
the ``ci_check_status`` shape.

**This is a CI check, not a periodic sweep.** ``Dev10x:plugin-doctor``
lists "running periodically" among its anti-patterns because a repeat
run re-prompts for findings the user already dismissed. That objection
is about re-prompting a person, and it is answered here twice over: this
command never prompts, and the acceptance catalog gives a dismissal
somewhere durable to live. It is still not licence to schedule the
command against a developer's machine — run it where a change to the
catalog is what triggers it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from dev10x.domain.common.result import SuccessResult
from dev10x.skills.doctor.acceptance import load_doctor_acceptances
from dev10x.skills.doctor.context import build_context
from dev10x.skills.doctor.runner import DEFAULT_THRESHOLD, SEVERITY_ORDER, run_doctor


@click.group()
def doctor() -> None:
    """Assert Dev10x catalog health with no agent in the loop."""


@doctor.command(name="run")
@click.option(
    "--threshold",
    type=click.Choice(SEVERITY_ORDER),
    default=DEFAULT_THRESHOLD,
    show_default=True,
    help="Lowest severity that fails the run. Suggestions never block by default.",
)
@click.option(
    "--project-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Checkout whose .claude/ settings are swept (default: the working directory).",
)
def run(threshold: str, project_root: Path | None) -> None:
    """Sweep every strategy and print the findings as JSON.

    Exits 1 when any unaccepted finding is at or above ``--threshold``,
    and 2 when the sweep itself could not complete.
    """
    result = run_doctor(
        context=build_context(project_root=project_root),
        accepted=load_doctor_acceptances(),
        threshold=threshold,  # type: ignore[arg-type]
    )
    if not isinstance(result, SuccessResult):
        click.echo(json.dumps(result.to_dict(), indent=2))
        sys.exit(2)
    payload = result.to_dict()
    click.echo(json.dumps(payload, indent=2))
    if payload["blocking"]:
        sys.exit(1)


__all__ = ["doctor"]
