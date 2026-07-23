from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
def spec() -> None:
    """Inspect canonical specs at docs/specs/<TICKET-ID>.md (GH-172)."""


@spec.command(name="drift")
@click.argument("spec_path", type=click.Path(path_type=Path))
@click.option(
    "--project-root",
    "project_root",
    type=click.Path(path_type=Path),
    default=None,
    help="Project root to check code references against (default: cwd).",
)
def drift(*, spec_path: Path, project_root: Path | None) -> None:
    """Report structural/behavioural drift between SPEC_PATH and the code.

    Exit codes: 0 = no drift, 1 = structural drift only,
    2 = behavioural drift present.
    """
    from dev10x.spec.drift_detector import detect_drift

    resolved_root = project_root if project_root is not None else Path.cwd()
    report = detect_drift(spec_path=spec_path, project_root=resolved_root)

    if not report.has_drift:
        click.echo(f"No drift detected: {spec_path}")
        sys.exit(0)

    for signal in report.signals:
        click.echo(f"[{signal.kind}] {signal.section}: {signal.detail}")

    sys.exit(2 if report.has_behavioural else 1)
