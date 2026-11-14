from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok

from dev10x.comm.chatbus.authz import Allowlist
from dev10x.comm.chatbus.backfill import Page, SubscriptionRecovery
from dev10x.comm.chatbus.daemon import (
    ChatBusDaemon,
    DaemonLimits,
    DaemonPorts,
    Dispatching,
    PollSource,
    PubSubSource,
    TickReport,
    start_daemon,
    stored_events,
)
from dev10x.comm.chatbus.dispatch import DispatchConfig, Outcome
from dev10x.comm.chatbus.events import REACTION_CREATED
from dev10x.comm.chatbus.sources.poll import WatchedSpace
from dev10x.comm.chatbus.sources.pubsub import (
    ReceivedMessage,
    RenewalAction,
    SubscriptionSpec,
    SubscriptionState,
)
from dev10x.comm.overwatch.launcher import Launched
from tests.comm.chatbus.factories import NOW, SPACE, expect_error, unwrap

OWNER = "users/1"
NEWCOMER = "users/9"
BOT = "users/500"
THREAD = f"{SPACE}/threads/t1"
TOPIC = "projects/p/topics/chat"
PULL_SUBSCRIPTION = "projects/p/subscriptions/chat"
OWNER_ONLY = Allowlist(owner=OWNER, trusted=frozenset(), logins={})
NEW_OWNER = Allowlist(owner=NEWCOMER, trusted=frozenset(), logins={})


def raw_message(
    *,
    number: int,
    text: str = "start fix the login page",
    sender: str = OWNER,
    minutes_ago: int = 1,
    addressed: bool = True,
) -> dict[str, Any]:
    name = f"{SPACE}/messages/m{number:03d}"
    mention = {"type": "USER_MENTION", "userMention": {"user": {"name": BOT}}}
    return {
        "name": name,
        "createTime": (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sender": {"name": sender, "type": "HUMAN"},
        "text": text,
        "argumentText": text,
        "thread": {"name": THREAD},
        "annotations": [mention] if addressed else [],
    }


def ticket_reaction(*, number: int) -> ReceivedMessage:
    reaction = {
        "name": f"{SPACE}/messages/m{number:03d}/reactions/r1",
        "user": {"name": OWNER},
        "emoji": {"unicode": "🎫"},
    }
    return ReceivedMessage(
        ack_id=f"ack-{number}",
        data=json.dumps({"reaction": reaction}).encode(),
        attributes={"ce-type": REACTION_CREATED, "ce-time": "2026-11-06T11:59:30Z"},
    )


@dataclass
class FakeReader:
    pages: dict[str, Result[list[Mapping[str, Any]]]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(
        self, *, space: str, thread: str | None, max_results: int
    ) -> Result[list[Mapping[str, Any]]]:
        self.calls.append(space)
        return self.pages.get(space, ok([]))


@dataclass
class FakeTargets:
    targets: list[WatchedSpace] = field(default_factory=lambda: [WatchedSpace(space=SPACE)])

    def __call__(self, *, now: datetime) -> Sequence[WatchedSpace]:
        return self.targets


@dataclass
class FakePuller:
    batches: list[Result[list[ReceivedMessage]]] = field(default_factory=list)
    acked: list[str] = field(default_factory=list)

    def pull(self, *, subscription: str, max_messages: int) -> Result[list[ReceivedMessage]]:
        return self.batches.pop(0) if self.batches else ok([])

    def ack(self, *, subscription: str, ack_ids: Sequence[str]) -> Result[None]:
        self.acked += ack_ids
        return ok(None)


@dataclass
class FakeSubscriptions:
    created: Result[SubscriptionState] = field(
        default_factory=lambda: ok(
            SubscriptionState(
                name="subscriptions/s1", state="ACTIVE", expire_time=NOW + timedelta(hours=4)
            )
        )
    )
    calls: list[str] = field(default_factory=list)

    def get(self, *, name: str) -> Result[SubscriptionState | None]:
        self.calls.append("get")
        return ok(
            SubscriptionState(name=name, state="ACTIVE", expire_time=NOW + timedelta(hours=4))
        )

    def create(self, *, spec: SubscriptionSpec) -> Result[SubscriptionState]:
        self.calls.append("create")
        return self.created

    def renew(self, *, name: str) -> Result[SubscriptionState]:
        self.calls.append("renew")
        return ok(
            SubscriptionState(name=name, state="ACTIVE", expire_time=NOW + timedelta(hours=5))
        )

    def reactivate(self, *, name: str) -> Result[SubscriptionState]:
        self.calls.append("reactivate")
        return self.created


@dataclass
class FakeHistory:
    messages: Result[Page] = field(default_factory=lambda: ok(Page(items=[])))
    reads: int = 0

    def list_messages(
        self,
        *,
        space: str,
        since: datetime,
        threads: tuple[str, ...],
        page_size: int,
        page_token: str | None,
    ) -> Result[Page]:
        self.reads += 1
        return self.messages

    def list_reactions(
        self, *, message: str, page_size: int, page_token: str | None
    ) -> Result[Page]:
        return ok(Page(items=[]))


@dataclass
class FakeNotifier:
    def request_approval(
        self, *, owner: str, work_item_id: int, requester: str, verb: str
    ) -> Result[str]:
        return ok(f"spaces/DM/messages/approval{work_item_id}")


@dataclass
class FakeLauncher:
    spawns: list[str] = field(default_factory=list)

    def agent_states(self) -> Result[dict[str, str]]:
        return ok({})

    def spawn(self, *, branch: str) -> Result[Launched]:
        self.spawns.append(branch)
        return ok(Launched(pane_id="w1:p1", agent="chat-agent", path="/wt/item"))

    def prompt(self, *, agent: str, text: str) -> Result[None]:
        return ok(None)


@dataclass
class FakeLoader:
    results: list[Result[Allowlist]] = field(default_factory=lambda: [ok(OWNER_ONLY)])
    reasons: list[str] = field(default_factory=list)

    def __call__(self, *, reason: str) -> Result[Allowlist]:
        self.reasons.append(reason)
        return self.results.pop(0)


@dataclass
class Fakes:
    reader: FakeReader = field(default_factory=FakeReader)
    targets: FakeTargets = field(default_factory=FakeTargets)
    puller: FakePuller = field(default_factory=FakePuller)
    subscriptions: FakeSubscriptions = field(default_factory=FakeSubscriptions)
    history: FakeHistory = field(default_factory=FakeHistory)
    launcher: FakeLauncher = field(default_factory=FakeLauncher)
    loader: FakeLoader = field(default_factory=FakeLoader)


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


def _ports(
    *,
    fakes: Fakes,
    tmp_path: Path,
    history: bool = True,
    pubsub: bool = True,
    dispatching: bool = True,
    bot_user: str = BOT,
) -> DaemonPorts:
    return DaemonPorts(
        bot_user=bot_user,
        notifier=FakeNotifier(),
        load_allowlist=fakes.loader,
        poll=PollSource(reader=fakes.reader, targets=fakes.targets),
        pubsub=PubSubSource(
            puller=fakes.puller,
            subscription=PULL_SUBSCRIPTION,
            renewal=SubscriptionRecovery(
                api=fakes.subscriptions, spec=SubscriptionSpec(topic=TOPIC)
            ),
        )
        if pubsub
        else None,
        history=fakes.history if history else None,
        dispatching=Dispatching(
            config=DispatchConfig(
                repo_root="/work/repo",
                bus_root=tmp_path / "bus",
                brief_dir=tmp_path / "briefs",
            ),
            launcher=fakes.launcher,
        )
        if dispatching
        else None,
    )


def _daemon(
    *,
    conn: sqlite3.Connection,
    ports: DaemonPorts,
    limits: DaemonLimits = DaemonLimits(),
) -> ChatBusDaemon:
    return unwrap(start_daemon(conn=conn, ports=ports, limits=limits, clock=lambda: NOW))


def _status(*, conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute("SELECT kind, status FROM work_items ORDER BY id").fetchall()
    return [(row[0], row[1]) for row in rows]


class TestStart:
    def test_loads_the_allowlist_once_at_start(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        assert (daemon.allowlist, fakes.loader.reasons) == (OWNER_ONLY, ["start"])

    def test_refuses_a_rejected_allowlist(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        fakes.loader.results = [err("found 2 owners")]
        refused = start_daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        assert expect_error(refused).error == "found 2 owners"

    def test_refuses_a_bot_user_that_is_not_a_user_name(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        refused = start_daemon(
            conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path, bot_user="dev10x-bot")
        )
        assert "users/<id>" in expect_error(refused).error
        assert fakes.loader.reasons == []


class TestFirstTick:
    @pytest.fixture
    def report(self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path) -> TickReport:
        fakes.reader.pages[SPACE] = ok([raw_message(number=1)])
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        return daemon.tick(now=NOW)

    def test_catches_up_at_start(self, report: TickReport) -> None:
        assert report.caught_up is not None

    def test_recovers_the_subscription_first(self, report: TickReport) -> None:
        assert report.subscription is not None
        assert report.subscription.action is RenewalAction.CREATED

    def test_stores_the_polled_message(self, report: TickReport) -> None:
        assert stored_events(report=report) == 1

    def test_authorizes_the_owner_command(
        self, report: TickReport, conn: sqlite3.Connection
    ) -> None:
        assert report.decided == 1
        assert _status(conn=conn) == [("privileged", "claimed")]

    def test_dispatches_it_to_a_new_session(self, report: TickReport, fakes: Fakes) -> None:
        assert [entry.outcome for entry in report.dispatched] == [Outcome.SPAWNED]
        assert fakes.launcher.spawns == ["chat/item-1"]

    def test_reports_no_failure(self, report: TickReport) -> None:
        assert report.failures == {}


class TestLaterTicks:
    @pytest.fixture
    def daemon(self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path) -> ChatBusDaemon:
        fakes.reader.pages[SPACE] = ok([raw_message(number=1, addressed=False)])
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        daemon.tick(now=NOW)
        return daemon

    def test_a_tick_on_schedule_does_not_catch_up(self, daemon: ChatBusDaemon) -> None:
        report = daemon.tick(now=NOW + timedelta(seconds=60))
        assert (report.caught_up, report.subscription) == (None, None)

    def test_a_wall_clock_gap_catches_up_again(self, daemon: ChatBusDaemon, fakes: Fakes) -> None:
        report = daemon.tick(now=NOW + timedelta(hours=3))
        assert report.caught_up is not None
        assert fakes.history.reads == 1

    def test_renews_the_subscription_when_due(self, daemon: ChatBusDaemon, fakes: Fakes) -> None:
        daemon.last_tick = NOW + timedelta(minutes=60)
        report = daemon.tick(now=NOW + timedelta(minutes=61))
        assert report.subscription is not None
        assert report.subscription.action is RenewalAction.RENEWED

    def test_an_ignored_event_is_classified_once(self, daemon: ChatBusDaemon) -> None:
        report = daemon.tick(now=NOW + timedelta(seconds=60))
        assert report.decided == 0
        assert daemon.decided_through == 1


class TestPubSub:
    def test_owner_reaction_becomes_privileged_work(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        fakes.puller.batches = [ok([ticket_reaction(number=7)])]
        daemon = _daemon(
            conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path, dispatching=False)
        )
        report = daemon.tick(now=NOW)
        assert (stored_events(report=report), report.decided) == (1, 1)
        assert fakes.puller.acked == ["ack-7"]
        assert _status(conn=conn) == [("privileged", "queued")]

    def test_a_failed_pull_does_not_stop_authorization(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        fakes.puller.batches = [err("pubsub.googleapis.com unreachable")]
        fakes.reader.pages[SPACE] = ok([raw_message(number=1)])
        daemon = _daemon(
            conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path, dispatching=False)
        )
        report = daemon.tick(now=NOW)
        assert report.failures == {"pubsub": "pubsub.googleapis.com unreachable"}
        assert report.decided == 1

    def test_an_ingest_failure_leaves_the_message_for_redelivery(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        conn.execute(
            """
            CREATE TRIGGER no_pubsub BEFORE INSERT ON events WHEN NEW.source = 'pubsub'
            BEGIN SELECT RAISE(ABORT, 'disk full'); END
            """
        )
        fakes.puller.batches = [ok([ticket_reaction(number=7)])]
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        report = daemon.tick(now=NOW)
        assert set(report.failures) == {"pubsub ingest"}
        assert fakes.puller.acked == []


class TestWithoutHistory:
    def test_start_up_still_recovers_the_subscription(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path, history=False))
        report = daemon.tick(now=NOW)
        assert report.caught_up is None
        assert fakes.subscriptions.calls == ["create"]

    def test_a_refused_subscription_is_reported(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        fakes.subscriptions.created = err("PERMISSION_DENIED")
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path, history=False))
        report = daemon.tick(now=NOW)
        assert report.failures == {"subscription": "PERMISSION_DENIED"}


class TestWithoutOptionalSources:
    def test_polls_alone(self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path) -> None:
        fakes.reader.pages[SPACE] = ok([raw_message(number=1)])
        ports = _ports(
            fakes=fakes, tmp_path=tmp_path, history=False, pubsub=False, dispatching=False
        )
        report = _daemon(conn=conn, ports=ports).tick(now=NOW)
        assert (report.pull, report.subscription, report.dispatched) == (None, None, ())
        assert _status(conn=conn) == [("privileged", "queued")]

    def test_runs_with_no_poll_source(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        ports = DaemonPorts(bot_user=BOT, notifier=FakeNotifier(), load_allowlist=fakes.loader)
        report = _daemon(conn=conn, ports=ports).tick(now=NOW)
        assert report == TickReport()


class TestFailuresAreIsolated:
    def test_a_failing_space_is_reported_by_name(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        fakes.reader.pages[SPACE] = err("gog timed out. Please try again.")
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        report = daemon.tick(now=NOW)
        assert report.failures == {f"poll {SPACE}": "gog timed out. Please try again."}

    def test_duplicate_targets_fail_catch_up_and_poll(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        fakes.targets.targets = [WatchedSpace(space=SPACE), WatchedSpace(space=SPACE)]
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        report = daemon.tick(now=NOW)
        assert set(report.failures) == {"catch-up", "poll"}

    def test_backfill_and_subscription_failures_are_reported(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        fakes.reader.pages[SPACE] = ok([raw_message(number=1, addressed=False)])
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        daemon.tick(now=NOW)
        fakes.history.messages = err("chat.googleapis.com unreachable")
        fakes.subscriptions.created = err("PERMISSION_DENIED")
        conn.execute("DELETE FROM subscriptions")
        report = daemon.tick(now=NOW + timedelta(hours=3))
        assert report.failures == {
            "subscription": "PERMISSION_DENIED",
            f"backfill {SPACE}": "chat.googleapis.com unreachable",
        }

    def test_an_authorization_error_is_retried_next_tick(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        conn.execute(
            """
            CREATE TRIGGER no_verdicts BEFORE INSERT ON commands
            BEGIN SELECT RAISE(ABORT, 'locked'); END
            """
        )
        fakes.reader.pages[SPACE] = ok([raw_message(number=1)])
        daemon = _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))
        report = daemon.tick(now=NOW)
        assert set(report.failures) == {"authorize"}
        assert daemon.decided_through == 0

    def test_an_unreadable_event_table_is_reported(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        ports = DaemonPorts(bot_user=BOT, notifier=FakeNotifier(), load_allowlist=fakes.loader)
        daemon = _daemon(conn=conn, ports=ports)
        conn.execute("DROP TABLE commands")
        report = daemon.tick(now=NOW)
        assert "cannot list new events" in report.failures["authorize"]

    def test_a_dispatch_error_is_reported(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        daemon = _daemon(
            conn=conn,
            ports=_ports(fakes=fakes, tmp_path=tmp_path),
            limits=DaemonLimits(dispatch_limit=0),
        )
        report = daemon.tick(now=NOW)
        assert set(report.failures) == {"dispatch"}


class TestReload:
    @pytest.fixture
    def daemon(self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path) -> ChatBusDaemon:
        return _daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path))

    def test_sighup_reloads_on_the_next_tick(self, daemon: ChatBusDaemon, fakes: Fakes) -> None:
        fakes.loader.results = [ok(NEW_OWNER)]
        daemon.request_reload()
        report = daemon.tick(now=NOW)
        assert (report.reloaded, daemon.allowlist) == (True, NEW_OWNER)
        assert fakes.loader.reasons == ["start", "reload"]

    def test_no_reload_without_a_request(self, daemon: ChatBusDaemon, fakes: Fakes) -> None:
        report = daemon.tick(now=NOW)
        assert (report.reloaded, fakes.loader.reasons) == (False, ["start"])

    def test_a_rejected_reload_is_reported(self, daemon: ChatBusDaemon, fakes: Fakes) -> None:
        fakes.loader.results = [err("found 0 owners")]
        daemon.request_reload()
        report = daemon.tick(now=NOW)
        assert report.failures == {"reload": "found 0 owners"}
        assert daemon.allowlist == OWNER_ONLY


class TestRunLoop:
    def test_ticks_until_stopped(
        self, conn: sqlite3.Connection, fakes: Fakes, tmp_path: Path
    ) -> None:
        stop = threading.Event()

        def clock() -> datetime:
            stop.set()
            return NOW

        daemon = unwrap(
            start_daemon(conn=conn, ports=_ports(fakes=fakes, tmp_path=tmp_path), clock=clock)
        )
        daemon.run(stop=stop)
        assert (daemon.last_tick, fakes.reader.calls) == (NOW, [SPACE])
