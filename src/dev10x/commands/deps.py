from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from dev10x.domain.common.result import ErrorResult


@click.group()
def deps() -> None:
    """Inspect declared dependency pins (GH-937).

    Companion to the GH-916 pin lint: the lint refuses an unbounded
    requirement, these commands report when a bounded one has gone
    stale.
    """


@deps.command(name="sweep")
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Repository root to scan (default: the effective working directory).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the raw report as JSON.")
@click.option(
    "--timeout",
    type=float,
    default=None,
    help="Per-request PyPI timeout in seconds (default: 15).",
)
@click.option(
    "--fail-on-stale/--no-fail-on-stale",
    default=True,
    help="Exit 1 when a stale pin is found, so a scheduled job can branch on it.",
)
def sweep(
    *,
    root: Path | None,
    as_json: bool,
    timeout: float | None,
    fail_on_stale: bool,
) -> None:
    """Report pinned dependencies whose current PyPI release is out of bounds.

    Reuses the GH-916 pin parsing, then queries the package index once per
    distribution. Needs network access; a lookup failure is reported in
    the report's `errors` list rather than aborting the sweep.
    """
    from functools import partial

    from dev10x import dependency_sweep
    from dev10x.subprocess_utils import effective_cwd

    scan_root = root if root is not None else Path(effective_cwd() or Path.cwd())
    fetch = partial(
        dependency_sweep.fetch_latest_version,
        timeout=timeout if timeout is not None else dependency_sweep.DEFAULT_TIMEOUT_SECONDS,
    )

    result = dependency_sweep.sweep(root=scan_root, fetch=fetch)
    if isinstance(result, ErrorResult):
        click.echo(f"❌ {result.error}", err=True)
        sys.exit(1)

    report = result.value
    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        click.echo(dependency_sweep.format_report(report))

    if fail_on_stale and report["stale"]:
        sys.exit(1)
