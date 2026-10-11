"""Observation logic for the dev10x:foreman overnight watcher.

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
import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.file_locks import atomic_append_line
from dev10x.domain.usage import blocks_report

log = logging.getLogger(__name__)

HEARTBEAT_GLOB = "status-*.md"
ESCALATIONS_GLOB = "escalations-*.md"
PARKED_FLAG = "parked"
MERGED_SHAS_FILE = "merged-shas"
RETIRED_FILE = "retired"
# `- <ISO timestamp> DONE: …` — the timestamp is optional, but when a
# leading token is present it must be a timestamp, so "NOT DONE" and
# "DONENESS" never read as a finished worker.
DONE_LINE = re.compile(r"^[-*\s]*(?:\d{4}-\d{2}-\d{2}T\S+\s+)?DONE\b")
SHA_PREFIX_MIN = 7
DEFAULT_CHUNK_MIN = 45
ESCALATION_PREFIXES = ("MERGE REQUEST", "ESCALATION")
PR_REFERENCE = re.compile(r"\bPR\s*#(\d+)", re.IGNORECASE)
SHA_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")
# The role lands in a file name: anything else could escape the run
# directory or produce a file the escalations glob never reads.
ROLE_NAME = re.compile(r"[A-Za-z0-9_-]+")


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
    return set(_listed_entries(path=scratchpad / MERGED_SHAS_FILE))


def _listed_entries(*, path: Path) -> list[str]:
    """One entry per line of a watchdog list file; ``#`` comments and blanks ignored."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [entry for line in lines if (entry := line.split("#")[0].strip())]


def heartbeat_file_name(*, chunk: str) -> str:
    """``status-<chunk>.md`` for a bare chunk id; a file name passes through."""
    if chunk.startswith("status-") and chunk.endswith(".md"):
        return chunk
    return f"status-{chunk}.md"


def is_done_line(*, line: str) -> bool:
    """Whether a heartbeat line is a worker's final ``DONE`` report (GH-1577)."""
    return DONE_LINE.match(line) is not None


def _last_line(*, path: Path) -> str:
    """Last non-blank line, or ``""`` when the file vanished since the glob."""
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except FileNotFoundError:
        return ""
    return lines[-1] if lines else ""


def _age_min(*, path: Path, now: float) -> int | None:
    """Minutes since ``path`` changed, or ``None`` when it vanished since the glob."""
    try:
        return int((now - path.stat().st_mtime) / 60)
    except FileNotFoundError:
        return None


def _listed_retired(*, scratchpad: Path) -> set[str]:
    return {
        heartbeat_file_name(chunk=entry)
        for entry in _listed_entries(path=scratchpad / RETIRED_FILE)
    }


def retired_heartbeats(*, scratchpad: Path) -> set[str]:
    """Heartbeat files whose worker has finished, so silence is expected.

    A finished worker never writes again, so its mtime only ages and the
    stall detector would re-alarm on it every window for the rest of the
    night (GH-1577). Two signals retire a file: its last line is a
    ``DONE`` report, or the watchdog listed the chunk in ``retired``. A
    line written after ``DONE`` makes the file live again — a worker
    resumed for a rebase is a worker that can stall.
    """
    listed = _listed_retired(scratchpad=scratchpad)
    return {
        status.name
        for status in scratchpad.glob(HEARTBEAT_GLOB)
        if status.name in listed or is_done_line(line=_last_line(path=status))
    }


def retire_chunk(*, scratchpad: Path, chunk: str) -> Result[str]:
    """Record ``chunk`` in ``retired`` so its silence stops raising STALL.

    The sanctioned way to quiet a finished worker that never wrote a
    ``DONE`` line. It appends to a watchdog-owned file and never touches
    the heartbeat itself: renaming or deleting run-dir files is the
    ``mv`` that froze a night run on a permission prompt (GH-1577).
    """
    name = heartbeat_file_name(chunk=chunk)
    if not (scratchpad / name).exists():
        return err(f"no heartbeat file {name} in {scratchpad}")
    atomic_append_line(scratchpad / RETIRED_FILE, name)
    return ok(name)


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


def heartbeat_ages(*, scratchpad: Path, now: float) -> dict[str, int]:
    """Minutes since each heartbeat file changed, keyed by file name.

    File mtime is the source of truth — a worker's self-reported
    timestamp text inside the file can be wrong, its mtime cannot.

    Per-file, not aggregated (GH-1064). The newest mtime across the run
    directory is not a liveness signal for anyone in particular: a
    foreman writing its own status every few minutes keeps that maximum
    fresh and hides every silent worker behind it. Three workers sat
    silent for 87–92 minutes before the aggregate finally aged past the
    threshold, and attributing the alarm still needed manual ``stat``
    forensics. One age per file makes the stall both detectable and
    already attributed.
    """
    return {
        status.name: age
        for status in scratchpad.glob(HEARTBEAT_GLOB)
        if (age := _age_min(path=status, now=now)) is not None
    }


EscalationCursor = dict[str, Counter[str]]


def _complete_lines(*, path: Path) -> Counter[str] | None:
    """Occurrences of each complete, non-blank line, or ``None`` if the file vanished.

    Only text through the last newline counts. A poll that lands
    between an append's write and its newline would otherwise record
    half an escalation as seen, so the finished line never appears —
    silently losing the one message this reader exists to deliver.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    complete = raw[: raw.rfind(b"\n") + 1].decode("utf-8", errors="replace")
    return Counter(line.strip() for line in complete.splitlines() if line.strip())


def escalation_baseline(*, scratchpad: Path) -> EscalationCursor:
    """Lines already in every escalation file, keyed by file name.

    Taken once at arm time so the watcher reports what is written from
    then on, rather than replaying a backlog written before it started.
    """
    cursor: EscalationCursor = {}
    for path in scratchpad.glob(ESCALATIONS_GLOB):
        counts = _complete_lines(path=path)
        if counts is not None:
            cursor[path.name] = counts
    return cursor


def new_escalation_lines(
    *,
    scratchpad: Path,
    cursor: EscalationCursor,
) -> tuple[list[str], EscalationCursor]:
    """Lines written to any escalation file since ``cursor`` was taken.

    Returns the new lines and the updated cursor — the caller holds the
    cursor so ``WatchState.observe`` stays pure.

    Reading the file is what makes the disk-first escalation discipline
    actually deliver (GH-1060). Agent-to-agent messages are best-effort:
    three MERGE REQUESTs from one night arrived hours late, batched
    together, long after the watchdog had recovered them by hand from
    disk. The file was already the authoritative channel; it simply had
    no reader, so each escalation cost ~26 minutes of dead time before
    someone thought to look.

    The cursor counts lines by content, never by byte offset (GH-1582).
    An overseer that inserts a line mid-file with Edit shifts every byte
    after it: an offset cursor then misses the inserted line and
    re-emits whichever older line slid past the old offset — that is
    how an already-merged ``MERGE REQUEST B2`` came back. Counting
    occurrences rather than keeping a set still delivers a line the
    overseer deliberately writes a second time.
    """
    lines: list[str] = []
    updated = dict(cursor)
    for path in sorted(scratchpad.glob(ESCALATIONS_GLOB)):
        current = _complete_lines(path=path)
        if current is None:
            continue
        seen = cursor.get(path.name, Counter())
        for line, count in current.items():
            lines.extend([line] * (count - seen[line]))
        # Keep the high-water count, so a rewrite that drops a line and
        # later restores it does not replay it as new.
        updated[path.name] = seen | current
    return lines, updated


def append_escalation(*, scratchpad: Path, role: str, line: str) -> Result[str]:
    """Append ``line`` as the last line of ``escalations-<role>.md`` (GH-1582).

    The sanctioned append primitive: Edit can only insert next to text
    it matches, which put each new request above older ones, and Write
    needs the whole file restated. The line must open with ``MERGE
    REQUEST`` or ``ESCALATION`` — anything else the watcher ignores, so
    accepting it would report delivery of a message nobody reads.
    """
    entry = line.strip()
    if "\n" in entry:
        return err("an escalation is one line; pass each line separately")
    if not entry.lstrip("-*#> ").upper().startswith(ESCALATION_PREFIXES):
        return err(f"an escalation line must open with one of {', '.join(ESCALATION_PREFIXES)}")
    if not ROLE_NAME.fullmatch(role):
        return err(f"role {role!r} must be letters, digits, '-' or '_'")
    if not scratchpad.is_dir():
        return err(f"no run directory {scratchpad}")
    path = scratchpad / f"escalations-{role}.md"
    if not entry.startswith(("-", "*")):
        entry = f"- {entry}"
    # A hand-written file may lack its final newline; appending straight
    # onto it would merge two requests into one unreadable line.
    existing = path.read_bytes() if path.exists() else b""
    if existing and not existing.endswith(b"\n"):
        entry = f"\n{entry}"
    atomic_append_line(path, entry)
    return ok(path.name)


def handled_merge_prs(*, scratchpad: Path) -> set[int]:
    """PR numbers named in ``merged-shas`` — e.g. ``<tip-sha>  # PR #1575``.

    The merge gate already records each landing there; naming the PR on
    the same line lets the watcher drop a replayed MERGE REQUEST for it
    without a network call (GH-1582).
    """
    try:
        text = (scratchpad / MERGED_SHAS_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    return {int(number) for number in PR_REFERENCE.findall(text)}


def is_handled_merge_request(
    *,
    entry: str,
    merged_shas: set[str] | frozenset[str],
    handled_prs: set[int] | frozenset[int],
) -> bool:
    """Whether a MERGE REQUEST names a PR or head SHA the run already merged."""
    if not entry.upper().startswith("MERGE REQUEST"):
        return False
    if any(int(number) in handled_prs for number in PR_REFERENCE.findall(entry)):
        return True
    return any(
        is_own_merge(sha=token, merged_shas=merged_shas) for token in SHA_TOKEN.findall(entry)
    )


def heartbeat_lines(*, scratchpad: Path, now: float) -> list[str]:
    listed = _listed_retired(scratchpad=scratchpad)
    lines: list[str] = []
    for status in sorted(scratchpad.glob(HEARTBEAT_GLOB)):
        age_min = _age_min(path=status, now=now)
        if age_min is None:
            continue
        last = _last_line(path=status)
        retired = status.name in listed or is_done_line(line=last)
        label = f"{status.name} retired" if retired else status.name
        lines.append(f"heartbeat: {label} age={age_min}min last={last or '(empty)'}")
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
    stall_alerts: dict[str, float] = field(default_factory=dict)
    stall_muted_until: float = field(default=0.0)
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
        heartbeat_ages: dict[str, int] | None = None,
        parked: bool = False,
        merged_shas: set[str] | frozenset[str] = frozenset(),
        escalation_lines: Sequence[str] = (),
        retired: set[str] | frozenset[str] = frozenset(),
        handled_prs: set[int] | frozenset[int] = frozenset(),
    ) -> list[str]:
        events: list[str] = []
        events.extend(self._park_events(now=now, block=block, parked=parked))
        events.extend(
            self._escalation_events(
                escalation_lines=escalation_lines,
                merged_shas=merged_shas,
                handled_prs=handled_prs,
            )
        )
        events.extend(
            self._stall_events(
                now=now, heartbeat_ages=heartbeat_ages, parked=parked, retired=retired
            )
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
            self.stall_muted_until = now + self.stall_min * 60
            if self.muted_milestones:
                cost = int(block.get("costUSD", 0))
                events.append(
                    f"QUOTA MILESTONE (parked rollup): {self.muted_milestones} muted "
                    f"while parked, block cost now ${cost}"
                )
                self.muted_milestones = 0
        self.was_parked = parked
        return events

    def _escalation_events(
        self,
        *,
        escalation_lines: Sequence[str],
        merged_shas: set[str] | frozenset[str],
        handled_prs: set[int] | frozenset[int],
    ) -> list[str]:
        """Surface MERGE REQUEST / ESCALATION lines written to disk (GH-1060).

        Emitted verbatim (minus list/heading punctuation) so the
        watchdog acts on the overseer's own wording within one poll
        interval instead of waiting on a message that may batch.

        A MERGE REQUEST for a PR the run already merged is dropped
        however it reached the reader (GH-1582): re-running the merge
        gate on a merged PR, or re-queueing it, is worse than silence.
        """
        events: list[str] = []
        for line in escalation_lines:
            entry = line.lstrip("-*#> ").strip()
            if not entry.upper().startswith(ESCALATION_PREFIXES):
                continue
            if is_handled_merge_request(
                entry=entry, merged_shas=merged_shas, handled_prs=handled_prs
            ):
                log.info("dropped already-merged escalation: %s", entry)
                continue
            events.append(entry)
        return events

    def _stall_events(
        self,
        *,
        now: float,
        heartbeat_ages: dict[str, int] | None,
        parked: bool,
        retired: set[str] | frozenset[str],
    ) -> list[str]:
        # A parked queue is idle by instruction — its expected-stale
        # heartbeats are not evidence of a stalled worker (GH-946).
        if parked or now < self.stall_muted_until:
            return []
        stall_window_s = self.stall_min * 60
        if not heartbeat_ages:
            # Grace period: before the first heartbeat file exists,
            # measure from watch start so a crew that never writes
            # still alarms.
            run_min = int((now - self.started_at) / 60)
            if run_min < self.stall_min or now - self.last_stall_alert < stall_window_s:
                return []
            self.last_stall_alert = now
            return [f"STALL: no heartbeat files, silent for {run_min} min"]
        # One event per silent file, each rate-limited on its own, so a
        # second worker going quiet is never swallowed by the first
        # worker's alert window (GH-1064).
        # A file that left the run directory carries no rate-limit state
        # forward — should the name return, it alarms on its own merits.
        self.stall_alerts = {
            name: at for name, at in self.stall_alerts.items() if name in heartbeat_ages
        }
        events: list[str] = []
        for name in sorted(heartbeat_ages):
            age = heartbeat_ages[name]
            # A finished worker is silent by design (GH-1577).
            if name in retired or age < self.stall_min:
                self.stall_alerts.pop(name, None)
                continue
            if now - self.stall_alerts.get(name, 0.0) < stall_window_s:
                continue
            self.stall_alerts[name] = now
            events.append(f"STALL {name}: silent {age} min")
        return events

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
