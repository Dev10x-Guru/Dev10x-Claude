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
@click.option("--chunk-min", default=45, show_default=True)
@click.option(
    "--token-budget",
    default=0,
    show_default=True,
    help="Per-block token allowance (0 = infer from completed blocks).",
)
def probe(
    *,
    scratchpad: Path,
    base_branch: str,
    repo: Path | None,
    chunk_min: int,
    token_budget: int,
) -> None:
    """One-shot status: quota block, burn projection, base SHA, heartbeats.

    The base line names ``origin/<branch>`` because that is what it
    reads — asked of the remote, never of this checkout's possibly
    stale local ref (GH-964). The burn line reports how many minutes
    of block budget the current rate leaves (GH-979).
    """
    from dev10x.skills.foreman import watch as watch_skill

    for line in watch_skill.probe_lines(
        scratchpad=scratchpad,
        base_branch=base_branch,
        repo=repo,
        chunk_min=chunk_min,
        token_budget=token_budget,
    ):
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
    "--chunk-min",
    default=45,
    show_default=True,
    help="Expected chunk runtime — QUOTA LOW fires when the budget runs out sooner.",
)
@click.option(
    "--token-budget",
    default=0,
    show_default=True,
    help="Per-block token allowance (0 = infer from completed blocks).",
)
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
    chunk_min: int,
    token_budget: int,
    max_rounds: int,
) -> None:
    """Event loop for the Monitor tool — one line per actionable event.

    Emits: STALL (heartbeat silence), BASE MOVED (origin base-branch
    advanced), QUOTA MILESTONE (block cost crossed a step), QUOTA
    RESET (new 5h block — resume interrupted crew), QUOTA LOW (the
    burn rate spends the block budget before the in-flight chunk can
    finish — checkpoint and park, GH-979).

    Two scratchpad files mute events that need no decision (GH-946):
    ``merged-shas`` (base-branch tips the run merged itself — matching
    BASE MOVED echoes are dropped) and ``parked`` (while present, STALL
    and QUOTA MILESTONE are suppressed and milestones roll up into one
    line on release).
    """
    from dev10x.skills.foreman import watch as watch_skill

    state = watch_skill.initial_watch_state(
        stall_min=stall_min,
        cost_step=cost_step,
        base_branch=base_branch,
        repo=repo,
        chunk_min=chunk_min,
        token_budget=token_budget,
    )
    click.echo(
        f"armed: base=origin/{base_branch}@{state.known_sha or 'unknown'} "
        f"block={state.known_block_id or 'none'} "
        f"parked={'yes' if watch_skill.queue_parked(scratchpad=scratchpad) else 'no'} "
        f"quota_ceiling_tokens={state.quota_ceiling_tokens or 'unknown'}"
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
            parked=watch_skill.queue_parked(scratchpad=scratchpad),
            merged_shas=watch_skill.own_merge_shas(scratchpad=scratchpad),
        )
        for event in events:
            click.echo(event)
        if events:
            sys.stdout.flush()
