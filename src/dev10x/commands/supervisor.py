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
from dev10x.comm.supervisor.dev_checkout import (
    DevCheckout,
    DevCheckoutError,
    pin_dev_checkout,
    read_dev_checkout,
    unpin_dev_checkout,
)
from dev10x.comm.supervisor.dev_launcher import DevLauncher, child_command
from dev10x.comm.supervisor.lessons import DEFAULT_KB_ROOT
from dev10x.comm.supervisor.probes import Snapshot, take_snapshot
from dev10x.comm.supervisor.server import SupervisorApp, make_server, run_collector
from dev10x.comm.supervisor.settings import SettingsStore
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

DEV_UNIT_TEMPLATE = """\
[Unit]
Description=Dev10x session supervisor page, dev checkout {checkout}

[Service]
ExecStart={exec_start} supervisor serve --dev --uv {uv}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

NOT_PINNED = "No dev checkout is pinned; run `dev10x supervisor dev pin --checkout PATH`."


def write_token(*, token: str, path: Path) -> None:
    atomic_write_text(path, token + "\n")
    os.chmod(path, 0o600)


def page_token(*, instance: paths.Instance) -> str:
    if instance is paths.Instance.RELEASE:
        return secrets.token_urlsafe(24)
    path = paths.page_token_path(instance=instance)
    try:
        saved = path.read_text(encoding="utf-8").strip()
    except OSError:
        saved = ""
    if saved:
        return saved
    fresh = secrets.token_urlsafe(24)
    write_token(token=fresh, path=path)
    return fresh


def build_app(
    *,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
    token: str,
    hook_token: str = "",
    instance: paths.Instance = paths.Instance.RELEASE,
) -> SupervisorApp:
    return SupervisorApp(
        store=DecisionStore(path=paths.decisions_path(instance=instance)),
        settings=SettingsStore(path=paths.settings_path(instance=instance)),
        bus_root=bus_root,
        kb_root=kb_root,
        log_path=paths.actions_log_path(instance=instance),
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
    token_file: Path | None = None,
) -> None:
    server = make_server(app=app, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    announce(
        f"Supervisor page: {url}?token={app.token}"
        if token_file is None
        else f"Supervisor page: {url} (token in {token_file})"
    )
    try:
        run_collector(app=app, interval=interval, stop=stop, provider=provider)
    finally:
        app.stop()
        server.shutdown()
        server.server_close()


def run_launcher(*, launcher: DevLauncher, stop: threading.Event, interval: float) -> None:
    launcher.run(stop=stop, interval=interval)


def _stop_on_signals() -> threading.Event:
    stop = threading.Event()

    def _stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    return stop


def _pinned_dev_checkout() -> DevCheckout | None:
    try:
        return read_dev_checkout()
    except DevCheckoutError as exc:
        raise click.ClickException(f"The dev checkout pin is unusable: {exc}") from exc


def _require_dev_checkout() -> DevCheckout:
    dev = _pinned_dev_checkout()
    if dev is None:
        raise click.ClickException(NOT_PINNED)
    return dev


def _uv_path() -> str:
    return shutil.which("uv") or "uv"


@click.group()
def supervisor() -> None:
    """Supervise local Claude Code sessions from one localhost page."""


@supervisor.command(name="serve")
@click.option(
    "--port",
    type=int,
    default=None,
    help=f"Defaults to {paths.DEFAULT_PORT}, or {paths.DEV_PORT} for the dev instance.",
)
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
@click.option(
    "--dev",
    "dev",
    is_flag=True,
    help="Run the dev page from the checkout pinned with `dev pin`, following its HEAD.",
)
@click.option(
    "--instance",
    type=click.Choice([instance.value for instance in paths.Instance]),
    default=paths.Instance.RELEASE.value,
    hidden=True,
)
@click.option("--uv", "uv", default=None, hidden=True)
def serve(
    *,
    port: int | None,
    interval: float,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
    auto_rename: bool,
    dev: bool,
    instance: str,
    uv: str | None,
) -> None:
    """Serve the supervisor page on 127.0.0.1 until stopped."""
    if dev:
        pinned = _require_dev_checkout()
        launcher = DevLauncher(
            command=child_command(
                dev=pinned,
                uv=uv or _uv_path(),
                interval=interval,
                kb_root=kb_root,
                bus_root=bus_root,
                relay_mailbox=relay_mailbox,
            ),
            checkout=pinned.checkout,
            announce=click.echo,
        )
        run_launcher(launcher=launcher, stop=_stop_on_signals(), interval=interval)
        return
    scope = paths.Instance(instance)
    hook_token = secrets.token_urlsafe(24)
    write_token(token=hook_token, path=paths.token_path(instance=scope))
    app = build_app(
        kb_root=kb_root,
        bus_root=bus_root,
        relay_mailbox=relay_mailbox,
        token=page_token(instance=scope),
        hook_token=hook_token,
        instance=scope,
    )
    app.auto_rename = auto_rename and scope is paths.Instance.RELEASE
    run_service(
        app=app,
        port=paths.default_port(instance=scope) if port is None else port,
        interval=interval,
        stop=_stop_on_signals(),
        provider=lambda: take_snapshot(bus_root=bus_root),
        announce=click.echo,
        token_file=None
        if scope is paths.Instance.RELEASE
        else paths.page_token_path(instance=scope),
    )


@supervisor.command(name="unit")
@click.option("--port", type=int, default=paths.DEFAULT_PORT, show_default=True)
@click.option("--dev", "dev", is_flag=True, help="Print the dev-checkout unit instead.")
def unit(*, port: int, dev: bool) -> None:
    """Print a systemd --user unit for the supervisor (does not install it)."""
    exec_start = shutil.which("dev10x") or "dev10x"
    if dev:
        pinned = _require_dev_checkout()
        click.echo(
            DEV_UNIT_TEMPLATE.format(
                exec_start=exec_start, uv=_uv_path(), checkout=pinned.checkout
            )
        )
        return
    click.echo(UNIT_TEMPLATE.format(exec_start=exec_start, port=port))


@supervisor.group(name="dev")
def dev_group() -> None:
    """Pin the local Dev10x checkout that serves the dev supervisor page."""


@dev_group.command(name="pin")
@click.option(
    "--checkout",
    type=click.Path(path_type=Path, file_okay=False, resolve_path=True),
    required=True,
)
@click.option("--port", type=int, default=paths.DEV_PORT, show_default=True)
def dev_pin(*, checkout: Path, port: int) -> None:
    """Remember CHECKOUT as the dev page's source, in overwatch.yaml."""
    try:
        pinned = pin_dev_checkout(checkout=checkout, port=port)
    except DevCheckoutError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Dev supervisor page: {pinned.checkout} on port {pinned.port}")


@dev_group.command(name="unpin")
def dev_unpin() -> None:
    """Forget the dev checkout; the dev page will not start."""
    removed = unpin_dev_checkout()
    click.echo("Dev checkout unpinned." if removed else "No dev checkout was pinned.")


@dev_group.command(name="status")
def dev_status() -> None:
    """Show the pinned dev checkout, if any."""
    pinned = _pinned_dev_checkout()
    if pinned is None:
        click.echo("No dev checkout is pinned.")
        return
    try:
        token = paths.page_token_path(instance=paths.Instance.DEV).read_text(encoding="utf-8")
    except OSError:
        token = ""
    page = (
        f"http://127.0.0.1:{pinned.port}/?token={token.strip()}"
        if token.strip()
        else "no token yet; start the dev page first"
    )
    click.echo(
        f"Dev supervisor page: {pinned.checkout} on port {pinned.port}\n"
        f"State: {paths.state_dir(instance=paths.Instance.DEV)}\n"
        f"Open: {page}"
    )


@dev_group.command(name="rotate-token")
def dev_rotate_token() -> None:
    """Drop the dev page's saved token; the next start issues a new one."""
    paths.page_token_path(instance=paths.Instance.DEV).unlink(missing_ok=True)
    click.echo("Dev page token dropped; restart the dev page to issue a new one.")
