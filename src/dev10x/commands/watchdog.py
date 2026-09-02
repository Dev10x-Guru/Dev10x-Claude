"""`dev10x watchdog` — wake a quota-paused night run (GH-1109).

Designed to run from cron/systemd, OUTSIDE any Claude session: a
platform pause takes the session and its event queue down together, so
nothing inside a session can notice its own block reset.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import click

from dev10x.domain.common.result import ErrorResult, Result


@click.group()
def watchdog() -> None:
    """Wake a quota-paused run when its 5h block resets.

    Run from a timer, not from inside a session — a paused session
    cannot observe its own reset.
    """


def _emit(result: Result[dict[str, Any]], *, as_json: bool) -> None:
    if isinstance(result, ErrorResult):
        # Under --json stdout is a parsed surface, so the error blob goes
        # there too: a consumer parses one channel and never sees empty
        # stdout on failure (script-domain-boundaries.md). The non-zero
        # exit still lets shell callers branch.
        click.echo(json.dumps(result.to_dict()), err=not as_json)
        raise SystemExit(1)
    payload = result.to_dict()
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        click.echo(f"{key}: {value}")


_json_option = click.option("--json", "as_json", is_flag=True, help="Emit the raw JSON payload.")
_run_root_option = click.option(
    "--run-root",
    "run_roots",
    multiple=True,
    required=True,
    type=click.Path(path_type=Path),
    help="Directory holding run directories. Repeatable.",
)
_stale_option = click.option(
    "--stale-after",
    default=20,
    show_default=True,
    help="Minutes of heartbeat silence before a run counts as paused.",
)


@watchdog.command(name="probe")
@_json_option
def probe(*, as_json: bool) -> None:
    """Report the active 5h block and whether a fresh one is available."""
    from dev10x.domain.watchdog import quota_state

    _emit(quota_state(), as_json=as_json)


@watchdog.command(name="sessions")
@_run_root_option
@_stale_option
@_json_option
def sessions(*, run_roots: tuple[Path, ...], stale_after: int, as_json: bool) -> None:
    """List run directories whose heartbeats have gone silent."""
    from dev10x.domain.watchdog import find_paused_runs

    _emit(
        find_paused_runs(
            run_roots=list(run_roots),
            stale_after=timedelta(minutes=stale_after),
        ),
        as_json=as_json,
    )


@watchdog.command(name="wake")
@_run_root_option
@_stale_option
@click.option(
    "--wake-command",
    required=True,
    help=(
        "Command to nudge a paused run; the run directory is appended "
        "as the final argument. Quote it as one string."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Report what would be woken without running the wake command.",
)
@_json_option
def wake_command_entry(
    *,
    run_roots: tuple[Path, ...],
    stale_after: int,
    wake_command: str,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Nudge every paused run once per block boundary.

    Idempotent: a latch records the boundary each run was last woken
    for, so a five-minute timer wakes a given run at most once per
    reset. A live session ignores a spurious nudge.
    """
    import shlex

    from dev10x.domain.watchdog import wake

    _emit(
        wake(
            run_roots=list(run_roots),
            wake_command=shlex.split(wake_command),
            stale_after=timedelta(minutes=stale_after),
            dry_run=dry_run,
        ),
        as_json=as_json,
    )
