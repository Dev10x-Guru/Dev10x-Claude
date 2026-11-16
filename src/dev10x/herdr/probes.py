from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import Any

from dev10x.core.domain.common.result import Result, err, ok
from dev10x.core.subprocess_utils import run
from dev10x.herdr.roster import RosterParseError, build_roster, parse_agents, parse_workspaces

log = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 10
WORKSPACE_LIST = ["herdr", "workspace", "list"]
AGENT_LIST = ["herdr", "agent", "list"]

Runner = Callable[..., subprocess.CompletedProcess[str]]


class HerdrProbeError(RuntimeError):
    pass


def _call(*, args: list[str], runner: Runner) -> str:
    try:
        result = runner(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise HerdrProbeError("herdr is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise HerdrProbeError(
            f"{' '.join(args)} timed out after {PROBE_TIMEOUT_SECONDS}s. "
            "Check `herdr status`, then try again."
        ) from exc
    if result.returncode != 0:
        raise HerdrProbeError(
            f"{' '.join(args)} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


def get_roster(
    *,
    cwd: str = "",
    repo_root: str = "",
    runner: Runner = run,
) -> Result[dict[str, Any]]:
    try:
        workspaces = parse_workspaces(raw=_call(args=WORKSPACE_LIST, runner=runner))
        agents = parse_agents(raw=_call(args=AGENT_LIST, runner=runner))
    except (HerdrProbeError, RosterParseError) as exc:
        log.warning("herdr roster probe failed", extra={"error": str(exc)})
        return err(str(exc))
    roster = build_roster(
        workspaces=workspaces,
        agents=agents,
        cwd=cwd,
        repo_root=repo_root,
    )
    return ok(roster.to_dict())
