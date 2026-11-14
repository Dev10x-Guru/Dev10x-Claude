from __future__ import annotations

import json
import signal
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.common.result import ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from tests.comm.chatbus.factories import unwrap

from dev10x.cli import cli
from dev10x.comm.chatbus.authz import Allowlist
from dev10x.comm.chatbus.daemon import ChatBusDaemon, DaemonLimits, DaemonPorts, utc_now
from dev10x.comm.chatbus.service import UnsentApprovalNotifier
from dev10x.comm.chatbus.store import open_store
from dev10x.comm.chatbus.unit import UNIT_NAME
from dev10x.commands import chatbus as command

BOT = "users/500"
OWNER_CONFIG = (
    f"users:\n  me:\n    chat_user_id: '1'\n    bus_role: owner\nchat_bus:\n  bot_user: {BOT}\n"
)


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(cli, ["chatbus", *args])


@pytest.fixture
def systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command, "service_state", lambda: "inactive")


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    return home


def test_is_listed_in_the_cli() -> None:
    assert "chatbus" in CliRunner().invoke(cli, ["--help"]).output


class TestStatus:
    @pytest.mark.usefixtures("systemctl")
    def test_works_before_the_store_exists(self) -> None:
        result = _invoke("status")
        assert result.exit_code == 0, result.output
        assert "Service: inactive" in result.output
        assert "not created yet" in result.output
        assert not Dev10xConfigDir.chat_bus_db().exists()

    @pytest.mark.usefixtures("systemctl")
    def test_works_against_an_empty_store(self) -> None:
        unwrap(open_store(path=Dev10xConfigDir.chat_bus_db())).close()
        result = _invoke("status", "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert (payload["service"], payload["exists"], payload["gaps"]) == ("inactive", True, [])
        assert payload["queue"]["queued"] == 0

    @pytest.mark.usefixtures("systemctl")
    def test_an_unopenable_store_fails(self) -> None:
        Dev10xConfigDir.chat_bus_db().mkdir(parents=True)
        result = _invoke("status")
        assert result.exit_code == 1
        assert "Cannot" in result.output


class TestInstallUnit:
    def test_writes_the_unit_under_the_config_home(self, config_home: Path) -> None:
        result = _invoke("install-unit", "--exec-start", "/opt/bin/dev10x")
        unit = config_home / "systemd" / "user" / UNIT_NAME
        assert result.exit_code == 0, result.output
        assert f"Unit created: {unit}" in result.output
        assert "systemctl --user enable --now dev10x-chatbus.service" in result.output
        assert "ExecStart=/opt/bin/dev10x chatbus run" in unit.read_text()

    def test_is_idempotent(self, config_home: Path) -> None:
        _invoke("install-unit", "--exec-start", "/opt/bin/dev10x")
        unit = config_home / "systemd" / "user" / UNIT_NAME
        before = unit.read_text()
        result = _invoke("install-unit", "--exec-start", "/opt/bin/dev10x")
        assert "Unit unchanged" in result.output
        assert unit.read_text() == before

    def test_defaults_to_the_dev10x_on_path(
        self, config_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(command.shutil, "which", lambda name: f"/found/{name}")
        _invoke("install-unit")
        unit = config_home / "systemd" / "user" / UNIT_NAME
        assert "ExecStart=/found/dev10x chatbus run" in unit.read_text()

    def test_an_unwritable_config_home_fails(self, config_home: Path) -> None:
        config_home.parent.mkdir(parents=True, exist_ok=True)
        config_home.write_text("not a directory")
        result = _invoke("install-unit", "--exec-start", "/opt/bin/dev10x")
        assert result.exit_code == 1
        assert "Cannot write the Chat bus unit" in result.output


@pytest.fixture
def gchat_config() -> Callable[[str], Path]:
    def write(content: str) -> Path:
        path = Dev10xConfigDir.gchat_config_yaml()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    return write


class TestRun:
    @pytest.fixture
    def ran(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
        calls: list[str] = []

        def fake_run(self: ChatBusDaemon, *, stop: threading.Event) -> None:
            calls.append(f"run owner={self.allowlist.owner}")

        def fake_handlers(*, daemon: ChatBusDaemon, stop: threading.Event) -> None:
            calls.append("signals")

        monkeypatch.setattr(ChatBusDaemon, "run", fake_run)
        monkeypatch.setattr(command, "install_signal_handlers", fake_handlers)
        yield calls

    def test_starts_the_loop_with_signal_handlers(
        self, gchat_config: Callable[[str], Path], ran: list[str]
    ) -> None:
        gchat_config(OWNER_CONFIG)
        result = _invoke("run")
        assert result.exit_code == 0, result.output
        assert ran == ["signals", "run owner=users/1"]
        assert Dev10xConfigDir.chat_bus_db().exists()

    def test_without_config_refuses_to_start(self, ran: list[str]) -> None:
        result = _invoke("run")
        assert result.exit_code == 1
        assert "No Google Chat config" in result.output
        assert ran == []

    def test_without_an_owner_refuses_to_start(
        self, gchat_config: Callable[[str], Path], ran: list[str]
    ) -> None:
        gchat_config(f"chat_bus:\n  bot_user: {BOT}\n")
        result = _invoke("run")
        assert result.exit_code == 1
        assert "Chat bus refused to start" in result.output
        assert ran == []

    def test_an_unopenable_store_refuses_to_start(
        self, gchat_config: Callable[[str], Path], ran: list[str]
    ) -> None:
        gchat_config(OWNER_CONFIG)
        Dev10xConfigDir.chat_bus_db().mkdir(parents=True)
        result = _invoke("run")
        assert result.exit_code == 1
        assert ran == []


class TestSignalHandlers:
    @pytest.fixture
    def handlers(self, tmp_path: Path) -> tuple[ChatBusDaemon, threading.Event, dict[int, Any]]:
        conn = unwrap(open_store(path=tmp_path / "bus.sqlite3"))
        daemon = ChatBusDaemon(
            conn=conn,
            ports=DaemonPorts(
                bot_user=BOT,
                notifier=UnsentApprovalNotifier(),
                load_allowlist=lambda *, reason: ok(
                    Allowlist(owner="users/1", trusted=frozenset(), logins={})
                ),
            ),
            allowlist=Allowlist(owner="users/1", trusted=frozenset(), logins={}),
            limits=DaemonLimits(),
            clock=utc_now,
        )
        stop = threading.Event()
        registered: dict[int, Any] = {}
        command.install_signal_handlers(
            daemon=daemon,
            stop=stop,
            register=lambda signum, handler: registered.update({signum: handler}),
        )
        yield daemon, stop, registered
        conn.close()

    def test_sighup_requests_a_reload(
        self, handlers: tuple[ChatBusDaemon, threading.Event, dict[int, Any]]
    ) -> None:
        daemon, stop, registered = handlers
        registered[signal.SIGHUP](signal.SIGHUP, None)
        assert (daemon.reload_pending, stop.is_set()) == (True, False)

    @pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
    def test_sigterm_and_sigint_stop_the_loop(
        self,
        handlers: tuple[ChatBusDaemon, threading.Event, dict[int, Any]],
        signum: int,
    ) -> None:
        daemon, stop, registered = handlers
        registered[signum](signum, None)
        assert (daemon.reload_pending, stop.is_set()) == (False, True)
