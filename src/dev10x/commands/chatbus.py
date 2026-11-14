"""`dev10x chatbus` — run, inspect and package the local Chat bus (ADR-0035 D9)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

import click

from dev10x.comm.chatbus.daemon import ChatBusDaemon, start_daemon, utc_now
from dev10x.comm.chatbus.service import CachedToken, build_ports, load_settings, user_token
from dev10x.comm.chatbus.status import get_status, render_status
from dev10x.comm.chatbus.store import open_store
from dev10x.comm.chatbus.unit import install_unit, render_unit, service_state, user_unit_dir
from dev10x.domain.common.result import ErrorResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir

LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"

SignalRegistrar = Callable[[int, Any], Any]


def install_signal_handlers(
    *,
    daemon: ChatBusDaemon,
    stop: threading.Event,
    register: SignalRegistrar = signal.signal,
) -> None:
    """SIGHUP reloads the allowlist on the next tick; SIGTERM and SIGINT stop the loop."""

    def _reload(signum: int, frame: FrameType | None) -> None:
        daemon.request_reload()

    def _stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    register(signal.SIGHUP, _reload)
    register(signal.SIGTERM, _stop)
    register(signal.SIGINT, _stop)


def _exec_start() -> str:
    return shutil.which("dev10x") or "dev10x"


@click.group()
def chatbus() -> None:
    """Run and inspect the local Google Chat bus daemon."""


@chatbus.command(name="run")
def run() -> None:
    """Run the Chat bus tick loop until stopped (the systemd unit's ExecStart)."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    config_path = Dev10xConfigDir.gchat_config_yaml()
    settings = load_settings(path=config_path)
    if isinstance(settings, ErrorResult):
        raise click.ClickException(settings.error)
    opened = open_store(path=Dev10xConfigDir.chat_bus_db())
    if isinstance(opened, ErrorResult):
        raise click.ClickException(opened.error)
    conn = opened.value
    try:
        started = start_daemon(
            conn=conn,
            ports=build_ports(
                settings=settings.value,
                config_path=config_path,
                token=CachedToken(mint=user_token),
            ),
        )
        if isinstance(started, ErrorResult):
            raise click.ClickException(f"Chat bus refused to start: {started.error}")
        stop = threading.Event()
        install_signal_handlers(daemon=started.value, stop=stop)
        started.value.run(stop=stop)
    finally:
        conn.close()


@chatbus.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="Print the status as JSON.")
def status(*, as_json: bool) -> None:
    """Show subscription expiry, cursor ages, queue depth and open gaps."""
    now = utc_now()
    current = get_status(path=Dev10xConfigDir.chat_bus_db(), now=now)
    if isinstance(current, ErrorResult):
        raise click.ClickException(current.error)
    service = service_state()
    if as_json:
        click.echo(json.dumps({"service": service, **current.value.to_dict(now=now)}, indent=2))
        return
    click.echo(render_status(status=current.value, now=now, service=service))


@chatbus.command(name="install-unit")
@click.option(
    "--exec-start",
    default=None,
    help="The dev10x executable the unit runs; defaults to the one on PATH.",
)
def install_unit_command(*, exec_start: str | None) -> None:
    """Write the dev10x-chatbus systemd user unit; enabling it is left to you."""
    installed = install_unit(
        unit_dir=user_unit_dir(environ=os.environ, home=Path.home()),
        content=render_unit(exec_start=exec_start or _exec_start()),
    )
    if isinstance(installed, ErrorResult):
        raise click.ClickException(installed.error)
    unit = installed.value
    click.echo(f"Unit {unit.change.value}: {unit.path}")
    click.echo("To start it now and at every login, run:")
    for command in unit.next_steps:
        click.echo(f"  {command}")
