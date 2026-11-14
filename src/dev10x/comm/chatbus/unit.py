"""The ``dev10x-chatbus`` systemd user unit (ADR-0035 D9).

``install_unit`` only writes the unit file; enabling it is left to the
user, who runs the printed ``systemctl --user`` commands. The unit
carries no secrets and passes no environment: the daemon reads its
Google credentials the same way ``gog`` and the Chat bot do.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.file_locks import atomic_write_text
from dev10x.subprocess_utils import run

log = logging.getLogger(__name__)

UNIT_NAME = "dev10x-chatbus.service"
SYSTEMCTL_TIMEOUT_SECONDS = 10
XDG_CONFIG_HOME = "XDG_CONFIG_HOME"

UNIT_TEMPLATE = """\
[Unit]
Description=Dev10x Chat bus: Google Chat events to local sessions
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_start} chatbus run
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""

ENABLE_COMMANDS = (
    "systemctl --user daemon-reload",
    f"systemctl --user enable --now {UNIT_NAME}",
)
RESTART_COMMAND = f"systemctl --user restart {UNIT_NAME}"

Runner = Callable[..., subprocess.CompletedProcess[str]]


class UnitChange(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class InstalledUnit:
    path: Path
    change: UnitChange

    @property
    def next_steps(self) -> tuple[str, ...]:
        if self.change is UnitChange.UPDATED:
            return (*ENABLE_COMMANDS, RESTART_COMMAND)
        return ENABLE_COMMANDS


def render_unit(*, exec_start: str) -> str:
    return UNIT_TEMPLATE.format(exec_start=exec_start)


def user_unit_dir(*, environ: Mapping[str, str], home: Path) -> Path:
    """Where systemd looks for user units: ``$XDG_CONFIG_HOME/systemd/user``."""
    configured = environ.get(XDG_CONFIG_HOME, "")
    root = Path(configured) if configured else home / ".config"
    return root / "systemd" / "user"


def install_unit(*, unit_dir: Path, content: str) -> Result[InstalledUnit]:
    """Write the unit file; an identical file is left alone, so a re-run changes nothing."""
    path = unit_dir / UNIT_NAME
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            return ok(InstalledUnit(path=path, change=UnitChange.UNCHANGED))
        unit_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, content)
    except OSError as exc:
        log.error("Cannot write the Chat bus unit %s: %s", path, exc)
        return err(f"Cannot write the Chat bus unit {path}: {exc}", path=str(path))
    change = UnitChange.CREATED if current is None else UnitChange.UPDATED
    log.info("Chat bus unit %s: %s", change.value, path)
    return ok(InstalledUnit(path=path, change=change))


def service_state(*, runner: Runner = run) -> str:
    """``systemctl --user is-active`` for the unit; never reads the manager's environment."""
    try:
        completed = runner(
            ["systemctl", "--user", "is-active", UNIT_NAME],
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return "unknown (systemctl not found)"
    except subprocess.TimeoutExpired:
        return f"unknown (systemctl did not answer in {SYSTEMCTL_TIMEOUT_SECONDS}s)"
    return (completed.stdout or "").strip() or f"unknown (exit {completed.returncode})"
