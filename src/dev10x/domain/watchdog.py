"""Wake a quota-paused night run when its usage block resets (GH-1109).

A platform quota pause kills the session **and** its event queue from the
session's point of view: `dev10x foreman watch` correctly emits
``QUOTA RESET`` when a new 5h block starts, but nothing delivers that
event into a paused session. Queued Monitor notifications and a due
``ScheduleWakeup`` do not revive it. In the 2026-08-31 run the block
reset 15 minutes after the freeze and the session still slept through
the following five hours, until a human nudged it.

So the actor that notices the reset must live **outside** every Claude
session — a cron/systemd timer calling this module. Everything here is
therefore importable and side-effect-free at module scope.

**What this module deliberately does not do.** It does not speak the
harness's cross-session socket protocol. That protocol is
harness-owned and undocumented, and reimplementing it would repeat the
mistake catalogued in ``skills/foreman/references/mcp-connectivity.md``
— a layer cannot own a transport it did not build. Instead the operator
supplies the wake command (``claude --resume``, a ``tmux send-keys``,
whatever their setup actually supports) and this module owns the three
parts that ARE ours: reading the quota block, finding run directories
that look paused, and firing at most once per boundary.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.cwd_resolver import resolve_cwd

log = logging.getLogger(__name__)

# A run directory holds one `status-*.md` heartbeat per active role.
HEARTBEAT_GLOB = "status-*.md"

# How long a run directory must be silent before it counts as paused
# rather than merely busy. The foreman stall threshold is lower; this is
# deliberately more conservative, because the cost of a false wake (one
# spurious nudge) is small but not zero, while the cost of a false
# negative is five hours of paid capacity.
DEFAULT_STALE_AFTER = timedelta(minutes=20)

# Bound every operator-supplied wake command. An unbounded wake would
# hang the timer invocation and silently stop all future wakes.
WAKE_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class RunCandidate:
    """A run directory that looks quota-paused."""

    run_dir: Path
    silent_for: timedelta
    last_heartbeat_at: datetime
    newest_heartbeat: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "silent_for_minutes": int(self.silent_for.total_seconds() / 60),
            "last_heartbeat_at": _iso(self.last_heartbeat_at),
            "newest_heartbeat": self.newest_heartbeat,
        }


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _state_path() -> Path:
    from dev10x.domain.dev10x_paths import Dev10xConfigDir

    return Dev10xConfigDir.home() / "watchdog-state.json"


def quota_state(*, now: datetime | None = None) -> Result[dict[str, Any]]:
    """Report the current 5h block and whether a fresh one is available.

    ``block_available`` is true when no block is currently active — the
    last recorded block's 5h window has elapsed, so the next request
    starts a new one. Derivable offline from the local transcripts,
    which is what lets this run with no session and no network.

    Note ``block_available`` alone is NOT the whole wake condition: a
    block opened by some *other* session after the run went silent also
    means capacity the paused run could be using. :func:`wake` combines
    the two — see :func:`_wake_reason`.
    """
    from dev10x.domain.usage import blocks_report

    moment = now or datetime.now(UTC)
    # Forward the injected clock: blocks_report decides activeness from
    # it, so omitting it would make the report internally inconsistent
    # (a caller-supplied `now` everywhere except the one field that
    # matters).
    report = blocks_report(active_only=True, now=moment)
    if isinstance(report, ErrorResult):
        return report

    blocks: list[dict[str, Any]] = report.value.get("blocks", [])
    active = blocks[0] if blocks else None
    return ok(
        {
            "now": _iso(moment),
            "active_block": active,
            "block_available": active is None,
        }
    )


def find_paused_runs(
    *,
    run_roots: list[Path],
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> Result[dict[str, Any]]:
    """Find run directories whose heartbeats have all gone silent.

    Uses heartbeat **mtime**, matching `foreman watch` — a worker's
    self-reported timestamp inside the file can be wrong, its mtime
    cannot. A directory with no heartbeat files at all is skipped rather
    than reported: it has not started, so there is nothing to wake.
    """
    if not run_roots:
        # A watchdog with nowhere to look would report "nothing paused"
        # and exit 0 forever — indistinguishable from working. Fail loud
        # instead; a silently-never-firing timer is the exact failure
        # class this tool exists to remove.
        return err("no run roots configured", candidates=[], count=0)

    moment = now or datetime.now(UTC)
    candidates: list[RunCandidate] = []
    for root in run_roots:
        if not root.is_dir():
            log.debug("watchdog: run root %s does not exist", root)
            continue
        for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            candidate = _inspect_run(run_dir=run_dir, now=moment, stale_after=stale_after)
            if candidate is not None:
                candidates.append(candidate)
    return ok(
        {
            "candidates": [c.as_dict() for c in candidates],
            "count": len(candidates),
        }
    )


def _inspect_run(*, run_dir: Path, now: datetime, stale_after: timedelta) -> RunCandidate | None:
    newest_name: str | None = None
    newest_mtime: float | None = None
    for beat in run_dir.glob(HEARTBEAT_GLOB):
        try:
            mtime = beat.stat().st_mtime
        except OSError:
            # A heartbeat deleted between glob and stat is normal against
            # a live run; it is not a reason to fail the whole sweep.
            continue
        if newest_mtime is None or mtime > newest_mtime:
            newest_mtime, newest_name = mtime, beat.name
    if newest_mtime is None or newest_name is None:
        return None
    last_seen = datetime.fromtimestamp(newest_mtime, tz=UTC)
    silent_for = now - last_seen
    if silent_for < stale_after:
        return None
    return RunCandidate(
        run_dir=run_dir,
        silent_for=silent_for,
        last_heartbeat_at=last_seen,
        newest_heartbeat=newest_name,
    )


def _block_key(quota: dict[str, Any]) -> str:
    """Identify the boundary a wake is attributed to.

    While a block is active its own id is the key, so a run is nudged at
    most once for that block. Between blocks there is no id to use, so
    the key falls back to the hour the gap was observed in — meaning a
    gap that persists across hours retries hourly. That retry is
    deliberate, not a leak: the first nudge can fail silently (a wake
    command that exits 0 without reaching anything), and an unused block
    is exactly the state worth trying again.
    """
    active = quota.get("active_block")
    if isinstance(active, dict):
        identity = active.get("id") or active.get("startTime")
        if identity:
            return f"block:{identity}"
    stamp = str(quota.get("now", ""))[:13]  # YYYY-MM-DDTHH
    return f"gap:{stamp}"


def _wake_reason(*, quota: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    """Why this candidate should be woken now, or None to leave it.

    Two conditions, because "no block is active" is too strict on its
    own (GH-1109 review). If the operator — or any unrelated session —
    touches Claude minutes after a reset, a block opens and the paused
    night run would otherwise stay asleep for that block's full five
    hours, which is precisely the window this tool was built for.
    """
    if quota.get("block_available"):
        return "no active block — capacity is free"
    active = quota.get("active_block")
    if not isinstance(active, dict):
        return None
    started = _parse_iso(active.get("startTime"))
    last_seen = _parse_iso(candidate.get("last_heartbeat_at"))
    if started is None or last_seen is None:
        return None
    if started > last_seen:
        # The run was already silent when this block opened, so the block
        # belongs to someone else and its capacity is going unused by the
        # run that is waiting for it.
        return "a new block opened after this run went silent"
    return None


def wake(
    *,
    run_roots: list[Path],
    wake_command: list[str],
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    dry_run: bool = False,
) -> Result[dict[str, Any]]:
    """Nudge every paused run once per boundary, when capacity is free.

    Idempotent per boundary: a latch in the Dev10x config home records
    the boundary each run directory was last woken for, so a timer
    firing every five minutes wakes a given run at most once per block.
    A live session ignores a spurious nudge; a paused one resumes and
    drains its queued watcher events, at which point the existing
    ``QUOTA RESET`` handling in the foreman instructions takes over.
    """
    if not wake_command:
        return err("no wake command configured", woken=[])

    quota = quota_state(now=now)
    if isinstance(quota, ErrorResult):
        return quota
    quota_value: dict[str, Any] = quota.value

    found = find_paused_runs(run_roots=run_roots, now=now, stale_after=stale_after)
    if isinstance(found, ErrorResult):
        return found

    block_key = _block_key(quota_value)
    candidates: list[dict[str, Any]] = found.value["candidates"]
    try:
        return ok(
            _wake_candidates(
                candidates=candidates,
                quota=quota_value,
                block_key=block_key,
                wake_command=wake_command,
                dry_run=dry_run,
            )
        )
    except OSError as ex:
        # LockTimeoutError subclasses OSError. A contended or unwritable
        # latch must surface as a Result, not a traceback out of a cron
        # job (ADR-0009).
        return err(f"watchdog latch unavailable: {ex}", woken=[])


def _wake_candidates(
    *,
    candidates: list[dict[str, Any]],
    quota: dict[str, Any],
    block_key: str,
    wake_command: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    """Decide and fire under ONE lock held across read → fire → write.

    Reading the latch unlocked and writing it locked would leave a
    check-then-act window: two overlapping timer ticks both read "not
    woken", both fire, and the run is double-nudged — defeating the only
    correctness guarantee this module offers.
    """
    from dev10x.domain.file_locks import atomic_write_text, file_lock

    path = _state_path()
    woken: list[dict[str, Any]] = []
    already: list[str] = []
    skipped: list[dict[str, Any]] = []

    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        data = _load_latch(path)
        entries: dict[str, Any] = data.setdefault("woken", {})
        for candidate in candidates:
            run_dir = candidate["run_dir"]
            reason = _wake_reason(quota=quota, candidate=candidate)
            if reason is None:
                skipped.append({"run_dir": run_dir, "reason": "block still active"})
                continue
            if entries.get(run_dir) == block_key:
                already.append(run_dir)
                continue
            if dry_run:
                woken.append({"run_dir": run_dir, "dry_run": True, "reason": reason})
                continue
            outcome = _fire(wake_command=wake_command, run_dir=run_dir)
            woken.append({"run_dir": run_dir, "reason": reason, **outcome})
            if outcome.get("ok"):
                entries[run_dir] = block_key
        if not dry_run:
            data["woken"] = _prune(entries)
            atomic_write_text(path, json.dumps(data, indent=2) + "\n")

    return {
        "block_key": block_key,
        "woken": woken,
        "already_woken": already,
        "skipped": skipped,
        "candidates_seen": len(candidates),
    }


def _load_latch(path: Path) -> dict[str, Any]:
    """Read the latch, treating an unparseable one as empty.

    The latch is a cache of "already nudged", not a record anything
    depends on. Discarding a corrupt one in-place — rather than
    unlinking and re-acquiring — keeps the whole read-decide-write cycle
    inside a single lock, and means an unreadable file cannot wedge
    every future wake.
    """
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        log.warning("watchdog: unreadable latch at %s; treating as empty", path)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _prune(entries: dict[str, Any]) -> dict[str, Any]:
    """Drop entries for run directories that no longer exist.

    Run dirs are ephemeral; without this the latch grows forever.
    """
    return {run_dir: key for run_dir, key in entries.items() if Path(run_dir).is_dir()}


def _fire(*, wake_command: list[str], run_dir: str) -> dict[str, Any]:
    """Run the operator's wake command with the run directory appended."""
    args = [*wake_command, run_dir]
    try:
        completed = subprocess.run(
            args,
            cwd=resolve_cwd(),
            capture_output=True,
            text=True,
            timeout=WAKE_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as ex:
        # SubprocessError covers TimeoutExpired — the case the timeout
        # above exists to create, and the one that must NOT escape as a
        # traceback from a cron job.
        log.warning("watchdog: wake command failed for %s: %s", run_dir, ex)
        return {"ok": False, "error": str(ex)}
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "").strip()[:400],
        }
    return {"ok": True}
