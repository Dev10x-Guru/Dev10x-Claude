"""Tests for `dev10x supervisor` (GH-1692)."""

from __future__ import annotations

import http.client
import stat
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from click.testing import CliRunner
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

from dev10x.cli import cli
from dev10x.comm.supervisor import paths
from dev10x.comm.supervisor.probes import Snapshot
from dev10x.commands import supervisor as command


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "config"
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(home))
    Dev10xConfigDir.reset_cache()
    yield home
    Dev10xConfigDir.reset_cache()


def test_unit_prints_execstart() -> None:
    result = CliRunner().invoke(cli, ["supervisor", "unit", "--port", "9000"])

    assert ("supervisor serve --port 9000" in result.output, "[Install]" in result.output) == (
        True,
        True,
    )


def test_cli_lists_supervisor() -> None:
    assert "supervisor" in CliRunner().invoke(cli, ["--help"]).output


def test_write_token_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "supervisor" / "token"

    command.write_token(token="abc", path=path)

    assert (path.read_text(), stat.S_IMODE(path.stat().st_mode)) == ("abc\n", 0o600)


def test_build_app_uses_config_paths(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb",
        bus_root=tmp_path / "bus",
        relay_mailbox="relay",
        token="t",
    )

    assert (app.log_path, app.store.all(), app.relay_mailbox) == (
        paths.actions_log_path(),
        [],
        "relay",
    )


def test_run_service_serves_until_stopped(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )
    stop = threading.Event()
    announced: list[str] = []
    ready = threading.Event()

    def announce(line: str) -> None:
        announced.append(line)
        ready.set()

    service = threading.Thread(
        daemon=True,
        target=command.run_service,
        kwargs={
            "app": app,
            "port": 0,
            "interval": 0.01,
            "stop": stop,
            "provider": lambda: Snapshot(sessions=[]),
            "announce": announce,
        },
    )
    service.start()
    try:
        ready.wait(timeout=5)
        url = urlsplit(announced[0].removeprefix("Supervisor page: "))
        connection = http.client.HTTPConnection("127.0.0.1", url.port, timeout=5)
        connection.request("GET", f"/api/sessions?{url.query}")
        status = connection.getresponse().status
        connection.close()
    finally:
        stop.set()
        service.join(timeout=5)

    assert (status, service.is_alive(), announced[0].endswith("/?token=t")) == (200, False, True)


def test_run_service_starts_rearm(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )
    stop = threading.Event()
    rearmed = threading.Event()

    service = threading.Thread(
        daemon=True,
        target=command.run_service,
        kwargs={
            "app": app,
            "port": 0,
            "interval": 0.01,
            "stop": stop,
            "provider": lambda: Snapshot(sessions=[]),
            "announce": lambda line: None,
            "rearm": rearmed.set,
        },
    )
    service.start()
    try:
        fired = rearmed.wait(timeout=5)
    finally:
        stop.set()
        service.join(timeout=5)

    assert fired is True


def test_build_rearm_disabled_by_empty_name(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )

    assert (
        command.build_rearm(app=app, agent_name="", interval=1.0, stop=threading.Event()) is None
    )


def test_build_rearm_runs_until_stopped(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )
    stop = threading.Event()
    stop.set()
    seen: dict[str, object] = {}

    def fake_run_rearm(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(command, "run_rearm", fake_run_rearm)
    rearm = command.build_rearm(app=app, agent_name="relay", interval=2.0, stop=stop)
    rearm()  # type: ignore[misc]
    owner = seen["attempt"].__self__  # type: ignore[attr-defined]

    assert (owner.agent_name, owner.relay_mailbox, seen["interval"], seen["stop"]) == (
        "relay",
        "relay",
        2.0,
        stop,
    )


def test_serve_wires_service(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run_service(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(command, "run_service", fake_run_service)
    handlers: dict[int, object] = {}
    monkeypatch.setattr(
        command.signal, "signal", lambda signum, handler: handlers.update({signum: handler})
    )

    result = CliRunner().invoke(
        cli,
        ["supervisor", "serve", "--port", "0", "--bus-root", str(tmp_path / "bus")],
    )
    handlers[command.signal.SIGTERM](command.signal.SIGTERM, None)  # type: ignore[operator]
    app = seen["app"]
    on_disk = paths.token_path().read_text().strip()

    assert (
        result.exit_code,
        seen["port"],
        on_disk == app.hook_token,  # type: ignore[attr-defined]
        on_disk != app.token,  # type: ignore[attr-defined]
        seen["stop"].is_set(),  # type: ignore[attr-defined]
        set(handlers) == {command.signal.SIGTERM, command.signal.SIGINT},
        app.auto_rename,  # type: ignore[attr-defined]
        callable(seen["rearm"]),
    ) == (0, 0, True, True, True, True, True, True)


def test_serve_can_skip_the_start_rename(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "run_service", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)

    CliRunner().invoke(
        cli,
        ["supervisor", "serve", "--no-rename", "--port", "0", "--bus-root", str(tmp_path / "bus")],
    )

    assert seen["app"].auto_rename is False  # type: ignore[attr-defined]


def test_serve_relay_agent_empty_disables_rearm(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "run_service", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)

    CliRunner().invoke(
        cli,
        ["supervisor", "serve", "--bus-root", str(tmp_path / "bus"), "--relay-agent", ""],
    )

    assert seen["rearm"] is None
