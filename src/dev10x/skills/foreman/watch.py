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

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.common.result import ErrorResult
from dev10x.domain.usage import blocks_report

log = logging.getLogger(__name__)

HEARTBEAT_GLOB = "status-*.md"
PARKED_FLAG = "parked"
MERGED_SHAS_FILE = "merged-shas"
SHA_PREFIX_MIN = 7
DEFAULT_CHUNK_MIN = 45


def queue_parked(*, scratchpad: Path) -> bool:
    """True while the run directory carries the ``parked`` flag file.

    The orchestrator touches the flag when it deliberately holds the
    queue (burn gate, supervisor hold) and removes it on release. A
    parked run has no decisions to make, so quota milestones and stall
    alarms are noise while it is present (GH-946).
    """
    return (scratchpad / PARKED_FLAG).exists()


def own_merge_shas(*, scratchpad: Path) -> set[str]:
    """SHAs the run itself put on the base branch, from ``merged-shas``.

    Whoever runs the merge gate appends the resulting base-branch tip
    SHA (one per line; ``#`` comments and blanks ignored). Base
    movement matching one of these is the run's own echo, not the
    external landing the watcher exists to report.
    """
    path = scratchpad / MERGED_SHAS_FILE
    if not path.exists():
        return set()
    shas: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        candidate = line.split("#")[0].strip()
        if candidate:
            shas.add(candidate)
    return shas


def is_own_merge(*, sha: str, merged_shas: set[str] | frozenset[str]) -> bool:
    """Whether ``sha`` matches a recorded own-merge SHA, either abbreviated.

    Both sides may be abbreviated (``git ls-remote`` returns full SHAs,
    a logged merge SHA is often short), so match by prefix in whichever
    direction is longer — never on a stub too short to be unambiguous.
    """
    if len(sha) < SHA_PREFIX_MIN:
        return False
    for known in merged_shas:
        if len(known) < SHA_PREFIX_MIN:
            continue
        if sha.startswith(known) or known.startswith(sha):
            return True
    return False


def active_quota_block() -> dict:
    """Return the active 5h usage block (ccusage-compatible), or {}."""
    result = blocks_report(active_only=True)
    if isinstance(result, ErrorResult):
        return {}
    blocks = result.value.get("blocks", [])
    return blocks[0] if blocks else {}


def block_identity(block: dict) -> str:
    return str(block.get("id") or block.get("startTime") or "")


def historical_token_ceiling() -> int:
    """Largest ``totalTokens`` any completed 5h block reached.

    The plan's real per-block allowance is not published anywhere the
    watcher can read, so the highest a finished block ever got is the
    only honest offline estimate of it — self-calibrating, and it can
    only ever be a floor (a block that was cut short by exhaustion
    records the exhaustion point itself). Returns ``0`` when there is
    no completed history, which callers must read as "unknowable" and
    stay silent about rather than guessing a ceiling (GH-979).
    """
    result = blocks_report(active_only=False)
    if isinstance(result, ErrorResult):
        return 0
    completed = [
        block
        for block in result.value.get("blocks", [])
        if not block.get("isActive") and not block.get("isGap")
    ]
    return max((int(block.get("totalTokens") or 0) for block in completed), default=0)


def minutes_to_quota_exhaustion(*, block: dict, ceiling_tokens: int) -> int | None:
    """Minutes until the current burn rate consumes ``ceiling_tokens``.

    ``None`` means unknowable — no ceiling estimate, or no measured
    burn rate yet (a block under a minute old has neither). ``0`` means
    the ceiling is already spent. Uses ``burnRate.tokensPerMinute``,
    the same figure ``usage_blocks`` reports.
    """
    if ceiling_tokens <= 0:
        return None
    rate = (block.get("burnRate") or {}).get("tokensPerMinute") or 0
    if rate <= 0:
        return None
    remaining_tokens = ceiling_tokens - int(block.get("totalTokens") or 0)
    if remaining_tokens <= 0:
        return 0
    return int(remaining_tokens / rate)


def base_branch_sha(*, base_branch: str, repo: Path | None = None) -> str:
    """Tip SHA of ``origin/<base_branch>`` as the REMOTE reports it (GH-964).

    ``git ls-remote`` asks the remote directly, so the answer never
    depends on when this checkout last fetched. That is deliberate: a
    local ``develop`` ref in an agent worktree is whatever it was at
    creation time, and merge-coordination tooling that reads it answers
    "what does this worktree think the base is" when the caller asked
    "what is the base". Callers must not substitute ``rev-parse
    <base_branch>``, and the rendered line names ``origin/<branch>`` so
    no reader has to guess which one it got.

    Returns ``""`` when the remote cannot be reached or the branch is
    absent — never a stale SHA. ``WatchState`` treats an empty SHA as
    "no observation", so a transient outage cannot fake a BASE MOVED.
    """
    completed = subprocess_utils.run(
        ["git", "ls-remote", "origin", f"refs/heads/{base_branch}"],
        cwd=str(repo) if repo is not None else None,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    line = (completed.stdout or "").strip()
    if not line:
        log.warning(
            "ls-remote returned no tip for origin/%s (rc=%s): base reported as unknown",
            base_branch,
            completed.returncode,
        )
        return ""
    return line.split("\t")[0]


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


def probe_lines(
    *,
    scratchpad: Path,
    base_branch: str,
    repo: Path | None = None,
    chunk_min: int = DEFAULT_CHUNK_MIN,
    token_budget: int = 0,
) -> list[str]:
    block = active_quota_block()
    projection = block.get("projection") or {}
    remaining = projection.get("remainingMinutes", block.get("remainingMinutes", "?"))
    identity = block_identity(block) or "none"
    cost = block.get("costUSD", 0.0)
    ceiling = token_budget if token_budget > 0 else historical_token_ceiling()
    to_budget = minutes_to_quota_exhaustion(block=block, ceiling_tokens=ceiling)
    lines = [
        f"quota: block={identity} cost=${cost:.0f} remaining_min={remaining}",
        f"burn: to_budget_min={'?' if to_budget is None else to_budget} "
        f"ceiling_tokens={ceiling or 'unknown'} chunk_min={chunk_min}",
        f"base origin/{base_branch}: "
        f"{base_branch_sha(base_branch=base_branch, repo=repo) or 'unknown'}",
    ]
    lines.append(
        f"parked: {'yes' if queue_parked(scratchpad=scratchpad) else 'no'} "
        f"own-merge shas: {len(own_merge_shas(scratchpad=scratchpad))}"
    )
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
    muted_milestones: int = field(default=0)
    was_parked: bool = field(default=False)
    chunk_min: int = field(default=DEFAULT_CHUNK_MIN)
    quota_ceiling_tokens: int = field(default=0)
    quota_low_alerted_block: str = field(default="")

    def observe(
        self,
        *,
        now: float,
        sha: str,
        block: dict,
        heartbeat_age_min: int | None,
        parked: bool = False,
        merged_shas: set[str] | frozenset[str] = frozenset(),
    ) -> list[str]:
        events: list[str] = []
        events.extend(self._park_events(now=now, block=block, parked=parked))
        events.extend(
            self._stall_events(now=now, heartbeat_age_min=heartbeat_age_min, parked=parked)
        )
        events.extend(self._base_events(sha=sha, merged_shas=merged_shas))
        events.extend(self._quota_events(block=block, parked=parked))
        events.extend(self._quota_low_events(block=block, parked=parked))
        return events

    def _park_events(self, *, now: float, block: dict, parked: bool) -> list[str]:
        events: list[str] = []
        if self.was_parked and not parked:
            # Crew heartbeats resume only after release, so give the
            # queue one stall window of grace before alarming again.
            self.last_stall_alert = now
            if self.muted_milestones:
                cost = int(block.get("costUSD", 0))
                events.append(
                    f"QUOTA MILESTONE (parked rollup): {self.muted_milestones} muted "
                    f"while parked, block cost now ${cost}"
                )
                self.muted_milestones = 0
        self.was_parked = parked
        return events

    def _stall_events(
        self,
        *,
        now: float,
        heartbeat_age_min: int | None,
        parked: bool,
    ) -> list[str]:
        # A parked queue is idle by instruction — its expected-stale
        # heartbeats are not evidence of a stalled worker (GH-946).
        if parked:
            return []
        # Grace period: before the first heartbeat file exists, measure
        # from watch start so a crew that never writes still alarms.
        run_min = int((now - self.started_at) / 60)
        effective_age = heartbeat_age_min if heartbeat_age_min is not None else run_min
        stall_window_s = self.stall_min * 60
        if effective_age < self.stall_min or now - self.last_stall_alert < stall_window_s:
            return []
        self.last_stall_alert = now
        return [f"STALL: newest heartbeat silent for {effective_age} min"]

    def _base_events(
        self,
        *,
        sha: str,
        merged_shas: set[str] | frozenset[str],
    ) -> list[str]:
        if not sha or sha == self.known_sha:
            return []
        event = f"BASE MOVED: {self.known_sha or 'unknown'} -> {sha}"
        self.known_sha = sha
        # An echo of the run's own merge needs no rebase relay and no
        # classification turn — rebaseline silently (GH-946).
        if is_own_merge(sha=sha, merged_shas=merged_shas):
            return []
        return [event]

    def _quota_events(self, *, block: dict, parked: bool) -> list[str]:
        events: list[str] = []
        block_id = block_identity(block)
        if block_id and block_id != self.known_block_id:
            if self.known_block_id:
                events.append(f"QUOTA RESET: new 5h block {block_id} — resume interrupted crew")
            self.known_block_id = block_id
            self.known_cost_bucket = 0
        bucket = int(block.get("costUSD", 0)) // self.cost_step
        if bucket > self.known_cost_bucket:
            self.known_cost_bucket = bucket
            if parked:
                self.muted_milestones += 1
            else:
                events.append(f"QUOTA MILESTONE: block cost crossed ${bucket * self.cost_step}")
        return events

    def _quota_low_events(self, *, block: dict, parked: bool) -> list[str]:
        """Warn once per block when the budget runs out mid-chunk (GH-979).

        The milestone events report spend after the fact; this one is
        the only forward-looking signal — without it a crew burns into
        the wall and freezes mid-task, which reads as a cluster of
        stalls rather than as exhaustion.
        """
        # A parked queue is already holding: it has no in-flight chunk
        # to protect, and the warning it would act on is the action.
        if parked:
            return []
        block_id = block_identity(block)
        if not block_id or block_id == self.quota_low_alerted_block:
            return []
        minutes = minutes_to_quota_exhaustion(
            block=block, ceiling_tokens=self.quota_ceiling_tokens
        )
        if minutes is None or minutes > self.chunk_min:
            return []
        # Exhaustion landing after the block rolls over is not
        # exhaustion — QUOTA RESET refills the budget first.
        block_remaining = int(block.get("remainingMinutes") or 0)
        if minutes >= block_remaining:
            return []
        self.quota_low_alerted_block = block_id
        return [
            f"QUOTA LOW: ~{minutes} min of block budget left at current burn "
            f"({block_remaining} min to reset, chunk needs ~{self.chunk_min}) — "
            f"checkpoint the in-flight chunk and park the queue"
        ]


def initial_watch_state(
    *,
    stall_min: int,
    cost_step: int,
    base_branch: str,
    repo: Path | None = None,
    started_at: float | None = None,
    chunk_min: int = DEFAULT_CHUNK_MIN,
    token_budget: int = 0,
) -> WatchState:
    block = active_quota_block()
    return WatchState(
        stall_min=stall_min,
        cost_step=cost_step,
        known_sha=base_branch_sha(base_branch=base_branch, repo=repo),
        known_block_id=block_identity(block),
        known_cost_bucket=int(block.get("costUSD", 0)) // cost_step,
        started_at=started_at if started_at is not None else time.time(),
        chunk_min=chunk_min,
        quota_ceiling_tokens=token_budget if token_budget > 0 else historical_token_ceiling(),
    )
