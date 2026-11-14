"""`dev10x overwatch` — the localhost session Overwatch page (GH-1692)."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

import click

from dev10x.comm.overwatch import paths
from dev10x.comm.overwatch.artifacts import ArtifactStore
from dev10x.comm.overwatch.decisions import DecisionStore
from dev10x.comm.overwatch.delivery import RELAY_MAILBOX
from dev10x.comm.overwatch.dev_checkout import (
    DevCheckout,
    DevCheckoutError,
    load_dev_checkout,
    pin_dev_checkout,
    read_dev_checkout,
    unpin_dev_checkout,
)
from dev10x.comm.overwatch.dev_watcher import DevPinWatcher, launcher_factory
from dev10x.comm.overwatch.lessons import DEFAULT_KB_ROOT
from dev10x.comm.overwatch.owner import ArtifactOwner, find_owner
from dev10x.comm.overwatch.probes import Snapshot, take_snapshot
from dev10x.comm.overwatch.publishers import load_publishers
from dev10x.comm.overwatch.rearm import RELAY_AGENT, RelayRearm, run_rearm
from dev10x.comm.overwatch.server import HOST, OverwatchApp, make_server, run_collector
from dev10x.comm.overwatch.settings import SettingsStore
from dev10x.comm.skills.bus.maildir import BUS_ROOT
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.file_locks import atomic_write_text

UNIT_TEMPLATE = """\
[Unit]
Description=Dev10x session Overwatch page

[Service]
ExecStart={exec_start} overwatch serve --port {port} --uv {uv}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

LIVE_NOTE = "a running `dev10x overwatch serve` picks this up within one poll, no restart"


def write_token(*, token: str, path: Path) -> None:
    atomic_write_text(path, token + "\n")
    os.chmod(path, 0o600)


def page_token(*, instance: paths.Instance) -> str:
    if not paths.profile(instance=instance).keeps_page_token:
        return secrets.token_urlsafe(24)
    path = paths.page_token_path(instance=instance)
    saved = paths.read_token(path=path)
    if saved:
        return saved
    fresh = secrets.token_urlsafe(24)
    write_token(token=fresh, path=path)
    return fresh


def page_url(*, port: int) -> str:
    return f"http://{HOST}:{port}/"


def instance_flag(*, instance: paths.Instance) -> str:
    return "" if instance is paths.Instance.RELEASE else f" --instance {instance.value}"


def build_app(
    *,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
    token: str,
    hook_token: str = "",
    instance: paths.Instance = paths.Instance.RELEASE,
) -> OverwatchApp:
    return OverwatchApp(
        store=DecisionStore(path=paths.decisions_path(instance=instance)),
        settings=SettingsStore(path=paths.settings_path(instance=instance)),
        artifacts=ArtifactStore(root=paths.artifacts_dir(instance=instance)),
        publishers_reader=load_publishers,
        instance_flag=instance_flag(instance=instance),
        bus_root=bus_root,
        kb_root=kb_root,
        log_path=paths.actions_log_path(instance=instance),
        token=token,
        hook_token=hook_token,
        relay_mailbox=relay_mailbox,
    )


def run_service(
    *,
    app: OverwatchApp,
    port: int,
    interval: float,
    stop: threading.Event,
    provider: Callable[[], Snapshot],
    announce: Callable[[str], None],
    token_file: Path | None = None,
    rearm: Callable[[], None] | None = None,
) -> None:
    server = make_server(app=app, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = page_url(port=server.server_address[1])
    announce(
        f"Overwatch page: {url}?token={app.token}"
        if token_file is None
        else f"Overwatch page: {url} (token in {token_file})"
    )
    if rearm is not None:
        threading.Thread(target=rearm, daemon=True).start()
    try:
        run_collector(app=app, interval=interval, stop=stop, provider=provider)
    finally:
        app.stop()
        server.shutdown()
        server.server_close()


def build_rearm(
    *,
    app: OverwatchApp,
    agent_name: str,
    interval: float,
    stop: threading.Event,
) -> Callable[[], None] | None:
    if not agent_name:
        return None
    rearm = RelayRearm(
        bus_root=app.bus_root,
        log_path=app.log_path,
        relay_mailbox=app.relay_mailbox,
        agent_name=agent_name,
    )

    def rearm_once() -> None:
        run_rearm(attempt=rearm.attempt, interval=interval, stop=stop)

    return rearm_once


def start_dev_watcher(
    *,
    watcher: DevPinWatcher,
    stop: threading.Event,
    interval: float,
) -> threading.Thread:
    thread = threading.Thread(
        target=watcher.run,
        kwargs={"stop": stop, "interval": interval},
        name="overwatch-dev-pin",
        daemon=True,
    )
    thread.start()
    return thread


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


def _uv_path() -> str:
    return shutil.which("uv") or "uv"


@click.group()
def overwatch() -> None:
    """Watch every local Claude Code session from one localhost page."""


@overwatch.command(name="serve")
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
    "--instance",
    type=click.Choice([instance.value for instance in paths.Instance]),
    default=paths.Instance.RELEASE.value,
    hidden=True,
)
@click.option("--uv", "uv", default=None, hidden=True)
@click.option(
    "--relay-agent",
    default=RELAY_AGENT,
    show_default=True,
    help="Herdr agent name to re-arm once at boot; empty disables it. Never on the dev page.",
)
def serve(
    *,
    port: int | None,
    interval: float,
    kb_root: Path,
    bus_root: Path,
    relay_mailbox: str,
    auto_rename: bool,
    instance: str,
    uv: str | None,
    relay_agent: str,
) -> None:
    """Serve the Overwatch page on 127.0.0.1 until stopped.

    While a checkout is pinned with `dev pin`, the dev page runs beside it.
    """
    scope = paths.Instance(instance)
    traits = paths.profile(instance=scope)
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
    app.auto_rename = auto_rename and traits.renames_sessions
    stop = _stop_on_signals()
    dev_thread = (
        start_dev_watcher(
            watcher=DevPinWatcher(
                make_launcher=launcher_factory(
                    uv=uv or _uv_path(),
                    interval=interval,
                    kb_root=kb_root,
                    bus_root=bus_root,
                    relay_mailbox=relay_mailbox,
                    announce=click.echo,
                ),
                announce=click.echo,
            ),
            stop=stop,
            interval=interval,
        )
        if traits.supervises_dev_page
        else None
    )
    try:
        run_service(
            app=app,
            port=traits.default_port if port is None else port,
            interval=interval,
            stop=stop,
            provider=lambda: take_snapshot(bus_root=bus_root),
            announce=click.echo,
            token_file=paths.page_token_path(instance=scope) if traits.keeps_page_token else None,
            rearm=build_rearm(
                app=app,
                agent_name=relay_agent if traits.rearms_relay else "",
                interval=interval,
                stop=stop,
            ),
        )
    finally:
        stop.set()
        if dev_thread is not None:
            dev_thread.join()


@overwatch.command(name="unit")
@click.option("--port", type=int, default=paths.DEFAULT_PORT, show_default=True)
def unit(*, port: int) -> None:
    """Print the systemd --user unit for Overwatch (does not install it).

    The one unit serves the release page, and the dev page whenever a
    checkout is pinned with `dev pin`.
    """
    exec_start = shutil.which("dev10x") or "dev10x"
    click.echo(UNIT_TEMPLATE.format(exec_start=exec_start, port=port, uv=_uv_path()))


@overwatch.group(name="dev")
def dev_group() -> None:
    """Pin the local Dev10x checkout that serves the dev Overwatch page."""


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
    click.echo(f"Dev Overwatch page: {pinned.checkout} on port {pinned.port}; {LIVE_NOTE}.")


@dev_group.command(name="unpin")
def dev_unpin() -> None:
    """Forget the dev checkout; a running service stops the dev page."""
    removed = unpin_dev_checkout()
    click.echo(
        f"Dev checkout unpinned; {LIVE_NOTE}." if removed else "No dev checkout was pinned."
    )


@dev_group.command(name="status")
def dev_status() -> None:
    """Show the pinned dev checkout, if any."""
    pinned = _pinned_dev_checkout()
    if pinned is None:
        click.echo("No dev checkout is pinned.")
        return
    token = paths.read_token(path=paths.page_token_path(instance=paths.Instance.DEV))
    page = (
        f"{page_url(port=pinned.port)}?token={token}"
        if token
        else "no token yet; start the dev page first"
    )
    click.echo(
        f"Dev Overwatch page: {pinned.checkout} on port {pinned.port}\n"
        f"State: {paths.state_dir(instance=paths.Instance.DEV)}\n"
        f"Open: {page}"
    )


@dev_group.command(name="rotate-token")
def dev_rotate_token() -> None:
    """Drop the dev page's saved token; the next start issues a new one."""
    paths.page_token_path(instance=paths.Instance.DEV).unlink(missing_ok=True)
    click.echo(
        "Dev page token dropped; the dev page issues a new one when it next starts "
        "(a new commit in the checkout, or `dev unpin` then `dev pin`)."
    )


def artifact_url(*, artifact_id: str, instance: paths.Instance) -> str:
    port = paths.profile(instance=instance).default_port
    if instance is paths.Instance.DEV:
        pinned = load_dev_checkout()
        port = pinned.port if pinned is not None else port
    token = paths.read_token(path=paths.page_token_path(instance=instance))
    query = f"?token={token}" if token else ""
    return f"{page_url(port=port)}{query}#/a/{artifact_id}"


def _unwrap(*, result: SuccessResult[Any] | ErrorResult) -> Any:
    if isinstance(result, ErrorResult):
        raise click.ClickException(result.error)
    return result.value


def _store(*, instance: str) -> ArtifactStore:
    return ArtifactStore(root=paths.artifacts_dir(instance=paths.Instance(instance)))


def _read_document(*, file: Path) -> object:
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"{file} is not a readable JSON document: {exc}") from exc


instance_option = click.option(
    "--instance",
    type=click.Choice([instance.value for instance in paths.Instance]),
    default=paths.Instance.RELEASE.value,
    show_default=True,
    help="Which Overwatch page holds the artifact.",
)


@overwatch.group(name="artifact")
def artifact_group() -> None:
    """Show an interactive artifact on the Overwatch page (GH-1938)."""


@artifact_group.command(name="put")
@click.argument("file", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option("--session", default="", help="Owning session name or id; found from PIDs if unset.")
@instance_option
def artifact_put(*, file: Path, session: str, instance: str) -> None:
    """Validate FILE and publish it as the next revision of its artifact."""
    document = _read_document(file=file)
    owner: ArtifactOwner = _unwrap(result=find_owner(start_pid=os.getpid(), session=session))
    saved = _unwrap(result=_store(instance=instance).put(document=document, owner=owner.to_dict()))
    url = artifact_url(artifact_id=saved["id"], instance=paths.Instance(instance))
    click.echo(f"Artifact {saved['id']} revision {saved['revision']}: {url}")


@artifact_group.command(name="url")
@click.argument("artifact_id")
@instance_option
def artifact_url_command(*, artifact_id: str, instance: str) -> None:
    """Print the page URL that opens ARTIFACT_ID."""
    click.echo(artifact_url(artifact_id=artifact_id, instance=paths.Instance(instance)))


@artifact_group.command(name="list")
@instance_option
def artifact_list(*, instance: str) -> None:
    """List artifacts, newest first."""
    summaries = _store(instance=instance).index()
    if not summaries:
        click.echo("No artifacts.")
        return
    for summary in summaries:
        owner = summary.owner["name"] or summary.owner["session_id"]
        click.echo(f"{summary.id}\tr{summary.revision}\t{summary.title}\t{owner}")


@artifact_group.command(name="shared")
@click.argument("artifact_id")
@click.option("--publisher", required=True, help="Publisher id from the share menu.")
@click.option("--url", "link", required=True, help="Where the artifact was published.")
@instance_option
def artifact_shared(*, artifact_id: str, publisher: str, link: str, instance: str) -> None:
    """Record where ARTIFACT_ID was published."""
    if load_publishers().find(publisher_id=publisher) is None:
        raise click.ClickException(f'No publisher "{publisher}"; see the page\'s share menu.')
    saved = _unwrap(
        result=_store(instance=instance).add_share(
            artifact_id=artifact_id, publisher=publisher, url=link
        )
    )
    click.echo(f"Artifact {artifact_id} revision {saved['revision']}: shared at {link}")
