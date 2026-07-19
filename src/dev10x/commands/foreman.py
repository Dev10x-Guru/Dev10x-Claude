from __future__ import annotations

import sys
import time
from pathlib import Path

import click


@click.group()
def foreman() -> None:
    """Watcher CLI for Dev10x:foreman overnight delivery runs.

    One pre-approved command surface for every loop/poll the harness
    needs — inline Monitor/Bash loop shapes prompt unpredictably and
    freeze unattended sessions (GH-890).
    """


@foreman.command(name="probe")
@click.option(
    "--scratchpad",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Directory holding the run's status-*.md heartbeat files.",
)
@click.option("--base-branch", default="develop", show_default=True)
@click.option(
    "--repo",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Repository to read origin/<base-branch> from (default: CWD).",
)
def probe(*, scratchpad: Path, base_branch: str, repo: Path | None) -> None:
    """One-shot status: quota block, base-branch SHA, heartbeat ages."""
    from dev10x.skills.foreman import watch as watch_skill

    for line in watch_skill.probe_lines(scratchpad=scratchpad, base_branch=base_branch, repo=repo):
        click.echo(line)


@foreman.command(name="watch")
@click.option(
    "--scratchpad",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Directory holding the run's status-*.md heartbeat files.",
)
@click.option("--base-branch", default="develop", show_default=True)
@click.option(
    "--repo",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Repository to read origin/<base-branch> from (default: CWD).",
)
@click.option("--stall-min", default=25, show_default=True)
@click.option("--interval-s", default=150, show_default=True)
@click.option("--cost-step", default=50, show_default=True)
@click.option(
    "--max-rounds",
    default=0,
    show_default=True,
    help="Stop after N observation rounds (0 = run until killed).",
)
def watch(
    *,
    scratchpad: Path,
    base_branch: str,
    repo: Path | None,
    stall_min: int,
    interval_s: int,
    cost_step: int,
    max_rounds: int,
) -> None:
    """Event loop for the Monitor tool — one line per actionable event.

    Emits: STALL (heartbeat silence), BASE MOVED (origin base-branch
    advanced), QUOTA MILESTONE (block cost crossed a step), QUOTA
    RESET (new 5h block — resume interrupted crew).
    """
    from dev10x.skills.foreman import watch as watch_skill

    state = watch_skill.initial_watch_state(
        stall_min=stall_min,
        cost_step=cost_step,
        base_branch=base_branch,
        repo=repo,
    )
    click.echo(
        f"armed: base={state.known_sha or 'unknown'} block={state.known_block_id or 'none'}"
    )
    sys.stdout.flush()

    rounds = 0
    while max_rounds <= 0 or rounds < max_rounds:
        time.sleep(interval_s)
        rounds += 1
        now = time.time()
        events = state.observe(
            now=now,
            sha=watch_skill.base_branch_sha(base_branch=base_branch, repo=repo),
            block=watch_skill.active_quota_block(),
            heartbeat_age_min=watch_skill.newest_heartbeat_age_min(scratchpad=scratchpad, now=now),
        )
        for event in events:
            click.echo(event)
        if events:
            sys.stdout.flush()
