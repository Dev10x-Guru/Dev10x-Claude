"""Observation logic for the Dev10x:foreman overnight watcher.

Every loop, pipeline, and poll the foreman harness needs lives behind
the ``dev10x foreman`` CLI — never inline in a Monitor/Bash command.
Inline loop/pipeline shapes are permission-matched per call and can
prompt mid-night, freezing the watchdog turn until a human returns
(GH-890; the seven-hour lesson this module encodes).

``WatchState.observe`` is pure — it turns one round of observations
into zero or more event lines — so the night loop itself is a thin,
fully-tested shell around it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.common.result import ErrorResult
from dev10x.domain.usage import blocks_report

HEARTBEAT_GLOB = "status-*.md"


def active_quota_block() -> dict:
    """Return the active 5h usage block (ccusage-compatible), or {}."""
    result = blocks_report(active_only=True)
    if isinstance(result, ErrorResult):
        return {}
    blocks = result.value.get("blocks", [])
    return blocks[0] if blocks else {}


def block_identity(block: dict) -> str:
    return str(block.get("id") or block.get("startTime") or "")


def base_branch_sha(*, base_branch: str, repo: Path | None = None) -> str:
    completed = subprocess_utils.run(
        ["git", "ls-remote", "origin", f"refs/heads/{base_branch}"],
        cwd=str(repo) if repo is not None else None,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    line = (completed.stdout or "").strip()
    return line.split("\t")[0] if line else ""


def newest_heartbeat_age_min(*, scratchpad: Path, now: float) -> int | None:
    """Minutes since the freshest heartbeat file changed; None when none exist.

    File mtime is the source of truth — a worker's self-reported
    timestamp text inside the file can be wrong, its mtime cannot.
    """
    mtimes = [status.stat().st_mtime for status in scratchpad.glob(HEARTBEAT_GLOB)]
    if not mtimes:
        return None
    return int((now - max(mtimes)) / 60)


def heartbeat_lines(*, scratchpad: Path, now: float) -> list[str]:
    lines: list[str] = []
    for status in sorted(scratchpad.glob(HEARTBEAT_GLOB)):
        age_min = int((now - status.stat().st_mtime) / 60)
        content = status.read_text(encoding="utf-8").strip().splitlines()
        last = content[-1] if content else "(empty)"
        lines.append(f"heartbeat: {status.name} age={age_min}min last={last}")
    return lines


def probe_lines(*, scratchpad: Path, base_branch: str, repo: Path | None = None) -> list[str]:
    block = active_quota_block()
    projection = block.get("projection") or {}
    remaining = projection.get("remainingMinutes", block.get("remainingMinutes", "?"))
    identity = block_identity(block) or "none"
    cost = block.get("costUSD", 0.0)
    lines = [
        f"quota: block={identity} cost=${cost:.0f} remaining_min={remaining}",
        f"base {base_branch}: {base_branch_sha(base_branch=base_branch, repo=repo) or 'unknown'}",
    ]
    heartbeats = heartbeat_lines(scratchpad=scratchpad, now=time.time())
    lines.extend(heartbeats if heartbeats else ["heartbeat: no status files yet"])
    return lines


@dataclass
class WatchState:
    """Pure event derivation for one observation round of the night loop."""

    stall_min: int
    cost_step: int
    known_sha: str
    known_block_id: str
    known_cost_bucket: int
    started_at: float
    last_stall_alert: float = field(default=0.0)

    def observe(
        self,
        *,
        now: float,
        sha: str,
        block: dict,
        heartbeat_age_min: int | None,
    ) -> list[str]:
        events: list[str] = []
        events.extend(self._stall_events(now=now, heartbeat_age_min=heartbeat_age_min))
        events.extend(self._base_events(sha=sha))
        events.extend(self._quota_events(block=block))
        return events

    def _stall_events(self, *, now: float, heartbeat_age_min: int | None) -> list[str]:
        # Grace period: before the first heartbeat file exists, measure
        # from watch start so a crew that never writes still alarms.
        run_min = int((now - self.started_at) / 60)
        effective_age = heartbeat_age_min if heartbeat_age_min is not None else run_min
        stall_window_s = self.stall_min * 60
        if effective_age < self.stall_min or now - self.last_stall_alert < stall_window_s:
            return []
        self.last_stall_alert = now
        return [f"STALL: newest heartbeat silent for {effective_age} min"]

    def _base_events(self, *, sha: str) -> list[str]:
        if not sha or sha == self.known_sha:
            return []
        event = f"BASE MOVED: {self.known_sha or 'unknown'} -> {sha}"
        self.known_sha = sha
        return [event]

    def _quota_events(self, *, block: dict) -> list[str]:
        events: list[str] = []
        block_id = block_identity(block)
        if block_id and block_id != self.known_block_id:
            if self.known_block_id:
                events.append(f"QUOTA RESET: new 5h block {block_id} — resume interrupted crew")
            self.known_block_id = block_id
            self.known_cost_bucket = 0
        bucket = int(block.get("costUSD", 0)) // self.cost_step
        if bucket > self.known_cost_bucket:
            events.append(f"QUOTA MILESTONE: block cost crossed ${bucket * self.cost_step}")
            self.known_cost_bucket = bucket
        return events


def initial_watch_state(
    *,
    stall_min: int,
    cost_step: int,
    base_branch: str,
    repo: Path | None = None,
    started_at: float | None = None,
) -> WatchState:
    block = active_quota_block()
    return WatchState(
        stall_min=stall_min,
        cost_step=cost_step,
        known_sha=base_branch_sha(base_branch=base_branch, repo=repo),
        known_block_id=block_identity(block),
        known_cost_bucket=int(block.get("costUSD", 0)) // cost_step,
        started_at=started_at if started_at is not None else time.time(),
    )
