"""The Chat bus service loop: sources, backfill, authorization and dispatch (ADR-0035 D7, D9).

One tick runs the phases in a fixed order:

1. a pending ``SIGHUP`` reloads the allowlist;
2. at start-up, or after a wall-clock gap a sleep or a stop explains,
   catch-up recovers the subscription and backfills every watched
   space; otherwise the subscription is renewed when it is due;
3. the poll source reads the newest page of every watched space;
4. the Pub/Sub source pulls one batch of reactions;
5. every event without a verdict is authorized against the allowlist;
6. the dispatcher hands approved privileged items to a session.

A phase that fails is logged and reported; the next phase still runs,
and the next tick retries. Every adapter is injected, so the loop runs
in tests against fakes and never reaches Google, herdr or systemd.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from dev10x.comm.chatbus.authz import Allowlist, ApprovalNotifier, authorize
from dev10x.comm.chatbus.backfill import (
    BackfillLimits,
    CatchUpReport,
    ChatHistoryReader,
    SubscriptionRecovery,
    catch_up,
    catch_up_due,
)
from dev10x.comm.chatbus.dispatch import (
    DispatchConfig,
    Dispatched,
    SessionLauncher,
    dispatch_pending,
)
from dev10x.comm.chatbus.sources.poll import (
    PollLimits,
    PollTick,
    RawMessageReader,
    WatchedSpace,
    poll_tick,
)
from dev10x.comm.chatbus.sources.pubsub import (
    RENEW_EVERY,
    PubSubPuller,
    PullReport,
    SubscriptionStatus,
    ensure_subscription,
    pull_once,
    renewal_due,
)
from dev10x.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

DEFAULT_TICK = timedelta(seconds=60)
AUTHORIZE_BATCH = 200
DISPATCH_LIMIT = 10

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class TargetProvider(Protocol):
    def __call__(self, *, now: datetime) -> Sequence[WatchedSpace]:
        """The spaces, DMs and threads to read this tick, each space once."""


class AllowlistLoader(Protocol):
    def __call__(self, *, reason: str) -> Result[Allowlist]:
        """Load and log the effective allowlist (``authz.load_allowlist``)."""


@dataclass(frozen=True)
class PollSource:
    reader: RawMessageReader
    targets: TargetProvider


@dataclass(frozen=True)
class PubSubSource:
    puller: PubSubPuller
    subscription: str
    renewal: SubscriptionRecovery | None = None


@dataclass(frozen=True)
class Dispatching:
    config: DispatchConfig
    launcher: SessionLauncher


@dataclass(frozen=True)
class DaemonPorts:
    bot_user: str
    notifier: ApprovalNotifier
    load_allowlist: AllowlistLoader
    poll: PollSource | None = None
    pubsub: PubSubSource | None = None
    history: ChatHistoryReader | None = None
    dispatching: Dispatching | None = None


@dataclass(frozen=True)
class DaemonLimits:
    tick: timedelta = DEFAULT_TICK
    renew_every: timedelta = RENEW_EVERY
    authorize_batch: int = AUTHORIZE_BATCH
    dispatch_limit: int = DISPATCH_LIMIT
    poll: PollLimits = field(default_factory=PollLimits)
    backfill: BackfillLimits = field(default_factory=BackfillLimits)


@dataclass(frozen=True)
class TickReport:
    caught_up: CatchUpReport | None = None
    subscription: SubscriptionStatus | None = None
    poll: PollTick | None = None
    pull: PullReport | None = None
    decided: int = 0
    dispatched: tuple[Dispatched, ...] = ()
    reloaded: bool = False
    failures: Mapping[str, str] = field(default_factory=dict)


@dataclass
class _Tick:
    now: datetime
    caught_up: CatchUpReport | None = None
    subscription: SubscriptionStatus | None = None
    poll: PollTick | None = None
    pull: PullReport | None = None
    decided: int = 0
    dispatched: tuple[Dispatched, ...] = ()
    reloaded: bool = False
    failures: dict[str, str] = field(default_factory=dict)

    def fail(self, *, phase: str, error: str) -> None:
        log.warning("Chat bus %s failed: %s", phase, error)
        self.failures[phase] = error

    def report(self) -> TickReport:
        return TickReport(
            caught_up=self.caught_up,
            subscription=self.subscription,
            poll=self.poll,
            pull=self.pull,
            decided=self.decided,
            dispatched=self.dispatched,
            reloaded=self.reloaded,
            failures=dict(self.failures),
        )


class ChatBusDaemon:
    """Runs the tick loop over one open store; built by ``start_daemon``."""

    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        ports: DaemonPorts,
        allowlist: Allowlist,
        limits: DaemonLimits,
        clock: Clock,
    ) -> None:
        self.conn = conn
        self.ports = ports
        self.allowlist = allowlist
        self.limits = limits
        self.clock = clock
        self.last_tick: datetime | None = None
        self.decided_through = 0
        self._reload = threading.Event()

    def request_reload(self) -> None:
        """Ask the next tick to reload the allowlist; safe to call from a signal handler."""
        self._reload.set()

    @property
    def reload_pending(self) -> bool:
        return self._reload.is_set()

    def reload_allowlist(self) -> Result[Allowlist]:
        """The SIGHUP hook: swap in a freshly loaded allowlist."""
        loaded = self.ports.load_allowlist(reason="reload")
        if isinstance(loaded, ErrorResult):
            return loaded
        self.allowlist = loaded.value
        return loaded

    def run(self, *, stop: threading.Event) -> None:
        log.info("Chat bus running; tick every %ss", int(self.limits.tick.total_seconds()))
        while not stop.is_set():
            self.tick(now=self.clock())
            stop.wait(self.limits.tick.total_seconds())
        log.info("Chat bus stopped")

    def tick(self, *, now: datetime) -> TickReport:
        run = _Tick(now=now)
        self._apply_reload(run=run)
        targets = self._targets(now=now)
        if catch_up_due(last_tick=self.last_tick, now=now, tick=self.limits.tick):
            self._catch_up(run=run, targets=targets)
        else:
            self._renew(run=run, force=False)
        self._poll(run=run, targets=targets)
        self._pull(run=run)
        self._decide(run=run)
        self._dispatch(run=run)
        self.last_tick = now
        report = run.report()
        _log_tick(report=report)
        return report

    def _apply_reload(self, *, run: _Tick) -> None:
        if not self._reload.is_set():
            return
        self._reload.clear()
        reloaded = self.reload_allowlist()
        if isinstance(reloaded, ErrorResult):
            run.fail(phase="reload", error=reloaded.error)
            return
        run.reloaded = True

    def _targets(self, *, now: datetime) -> Sequence[WatchedSpace]:
        poll = self.ports.poll
        return [] if poll is None else poll.targets(now=now)

    def _renewal(self) -> SubscriptionRecovery | None:
        pubsub = self.ports.pubsub
        return None if pubsub is None else pubsub.renewal

    def _catch_up(self, *, run: _Tick, targets: Sequence[WatchedSpace]) -> None:
        history = self.ports.history
        if history is None:
            self._renew(run=run, force=True)
            return
        caught = catch_up(
            conn=self.conn,
            reader=history,
            targets=targets,
            now=run.now,
            subscription=self._renewal(),
            limits=self.limits.backfill,
        )
        if isinstance(caught, ErrorResult):
            run.fail(phase="catch-up", error=caught.error)
            return
        run.caught_up = caught.value
        run.subscription = caught.value.subscription
        if caught.value.subscription_error:
            run.fail(phase="subscription", error=caught.value.subscription_error)
        for space, error in caught.value.failures.items():
            run.fail(phase=f"backfill {space}", error=error)

    def _renew(self, *, run: _Tick, force: bool) -> None:
        renewal = self._renewal()
        if renewal is None:
            return
        due = renewal_due(
            conn=self.conn,
            target=renewal.spec.target_resource,
            now=run.now,
            every=self.limits.renew_every,
        )
        if not (force or due):
            return
        ensured = ensure_subscription(
            conn=self.conn, api=renewal.api, spec=renewal.spec, now=run.now
        )
        if isinstance(ensured, ErrorResult):
            run.fail(phase="subscription", error=ensured.error)
            return
        run.subscription = ensured.value

    def _poll(self, *, run: _Tick, targets: Sequence[WatchedSpace]) -> None:
        poll = self.ports.poll
        if poll is None:
            return
        polled = poll_tick(
            conn=self.conn,
            reader=poll.reader,
            targets=targets,
            now=run.now,
            limits=self.limits.poll,
        )
        if isinstance(polled, ErrorResult):
            run.fail(phase="poll", error=polled.error)
            return
        run.poll = polled.value
        for space, error in polled.value.failures.items():
            run.fail(phase=f"poll {space}", error=error)

    def _pull(self, *, run: _Tick) -> None:
        pubsub = self.ports.pubsub
        if pubsub is None:
            return
        pulled = pull_once(
            conn=self.conn, puller=pubsub.puller, subscription=pubsub.subscription, now=run.now
        )
        if isinstance(pulled, ErrorResult):
            run.fail(phase="pubsub", error=pulled.error)
            return
        run.pull = pulled.value
        if pulled.value.failed_spaces:
            run.fail(
                phase="pubsub ingest",
                error=f"not stored, left for redelivery: {', '.join(pulled.value.failed_spaces)}",
            )

    def _undecided(self) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT id FROM events AS e
             WHERE id > ?
               AND NOT EXISTS (SELECT 1 FROM commands AS c WHERE c.event_id = e.id)
             ORDER BY id LIMIT ?
            """,
            (self.decided_through, self.limits.authorize_batch),
        ).fetchall()
        return [int(row[0]) for row in rows]

    def _decide(self, *, run: _Tick) -> None:
        try:
            pending = self._undecided()
        except sqlite3.Error as exc:
            run.fail(phase="authorize", error=f"cannot list new events: {exc}")
            return
        for event_id in pending:
            verdict = authorize(
                conn=self.conn,
                event_id=event_id,
                allowlist=self.allowlist,
                bot_user=self.ports.bot_user,
                notifier=self.ports.notifier,
                now=run.now,
            )
            if isinstance(verdict, ErrorResult):
                run.fail(phase="authorize", error=verdict.error)
                return
            self.decided_through = event_id
            run.decided += 1

    def _dispatch(self, *, run: _Tick) -> None:
        dispatching = self.ports.dispatching
        if dispatching is None:
            return
        dispatched = dispatch_pending(
            conn=self.conn,
            config=dispatching.config,
            launcher=dispatching.launcher,
            now=run.now,
            limit=self.limits.dispatch_limit,
        )
        if isinstance(dispatched, ErrorResult):
            run.fail(phase="dispatch", error=dispatched.error)
            return
        run.dispatched = tuple(dispatched.value)


def stored_events(*, report: TickReport) -> int:
    polled = (
        0
        if report.poll is None
        else sum(space.report.inserted for space in report.poll.spaces.values())
    )
    pulled = 0 if report.pull is None else report.pull.inserted
    return polled + pulled


def _log_tick(*, report: TickReport) -> None:
    stored = stored_events(report=report)
    busy = report.caught_up or stored or report.decided or report.dispatched
    log.log(
        logging.INFO if busy else logging.DEBUG,
        "Chat bus tick: %s, %d new event(s), %d decided, %d dispatched, %d failure(s)",
        "caught up" if report.caught_up else "live",
        stored,
        report.decided,
        len(report.dispatched),
        len(report.failures),
    )


def start_daemon(
    *,
    conn: sqlite3.Connection,
    ports: DaemonPorts,
    limits: DaemonLimits = DaemonLimits(),
    clock: Clock = utc_now,
) -> Result[ChatBusDaemon]:
    """Load the allowlist and build the daemon; a rejected allowlist refuses to start (D3)."""
    if not ports.bot_user.startswith("users/"):
        return err(
            f"The Chat bus needs the bot's users/<id> as bot_user, got {ports.bot_user!r}",
            bot_user=ports.bot_user,
        )
    loaded = ports.load_allowlist(reason="start")
    if isinstance(loaded, ErrorResult):
        return loaded
    return ok(
        ChatBusDaemon(conn=conn, ports=ports, allowlist=loaded.value, limits=limits, clock=clock)
    )
