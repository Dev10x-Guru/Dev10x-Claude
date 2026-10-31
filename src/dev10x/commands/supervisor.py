"""`dev10x supervisor` — the localhost session supervisor page (GH-1692)."""

from __future__ import annotations

import os
import secrets
import shutil
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType

import click

from dev10x.comm.skills.bus.maildir import BUS_ROOT
from dev10x.comm.supervisor import paths
from dev10x.comm.supervisor.decisions import DecisionStore
from dev10x.comm.supervisor.delivery import RELAY_MAILBOX
from dev10x.comm.supervisor.lessons import DEFAULT_KB_ROOT
from dev10x.comm.supervisor.probes import Snapshot, take_snapshot
from dev10x.comm.supervisor.server import SupervisorApp, make_server, run_collector
from dev10x.domain.file_locks import atomic_write_text

UNIT_TEMPLATE = """\
[Unit]
Description=Dev10x session supervisor page

[Service]
ExecStart={exec_start} supervisor serve --port {port}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def write_token(*, token: str, path: Path) -> None:
    atomic_write_text(path, token + "\n")
    os.chmod(path, 0o600)


def build_app(
    *,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
    token: str,
    hook_token: str = "",
) -> SupervisorApp:
    return SupervisorApp(
        store=DecisionStore(path=paths.decisions_path()),
        bus_root=bus_root,
        kb_root=kb_root,
        log_path=paths.actions_log_path(),
        token=token,
        hook_token=hook_token,
        relay_mailbox=relay_mailbox,
    )


def run_service(
    *,
    app: SupervisorApp,
    port: int,
    interval: float,
    stop: threading.Event,
    provider: Callable[[], Snapshot],
    announce: Callable[[str], None],
) -> None:
    server = make_server(app=app, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    announce(f"Supervisor page: http://127.0.0.1:{server.server_address[1]}/?token={app.token}")
    try:
        run_collector(app=app, interval=interval, stop=stop, provider=provider)
    finally:
        app.stop()
        server.shutdown()
        server.server_close()


@click.group()
def supervisor() -> None:
    """Supervise local Claude Code sessions from one localhost page."""


@supervisor.command(name="serve")
@click.option("--port", type=int, default=paths.DEFAULT_PORT, show_default=True)
@click.option("--interval", type=float, default=5.0, show_default=True)
@click.option("--kb-root", type=click.Path(path_type=Path), default=DEFAULT_KB_ROOT)
@click.option("--bus-root", type=click.Path(path_type=Path), default=BUS_ROOT)
@click.option("--relay-mailbox", default=RELAY_MAILBOX, show_default=True)
@click.option(
    "--rename/--no-rename",
    "auto_rename",
    default=True,
    show_default=True,
    help="Once at start, rename idle sessions with a generated name after their branch.",
)
def serve(
    *,
    port: int,
    interval: float,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
    auto_rename: bool,
) -> None:
    """Serve the supervisor page on 127.0.0.1 until stopped."""
    hook_token = secrets.token_urlsafe(24)
    write_token(token=hook_token, path=paths.token_path())
    app = build_app(
        kb_root=kb_root,
        bus_root=bus_root,
        relay_mailbox=relay_mailbox,
        token=secrets.token_urlsafe(24),
        hook_token=hook_token,
    )
    app.auto_rename = auto_rename
    stop = threading.Event()

    def _stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    run_service(
        app=app,
        port=port,
        interval=interval,
        stop=stop,
        provider=lambda: take_snapshot(bus_root=bus_root),
        announce=click.echo,
    )


@supervisor.command(name="unit")
@click.option("--port", type=int, default=paths.DEFAULT_PORT, show_default=True)
def unit(*, port: int) -> None:
    """Print a systemd --user unit for the supervisor (does not install it)."""
    click.echo(UNIT_TEMPLATE.format(exec_start=shutil.which("dev10x") or "dev10x", port=port))
