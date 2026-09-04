"""CI monitoring MCP tool implementations.

Wraps ci-check-status operations as MCP tools so skills can
check CI status without Bash allow-rule friction.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import async_run, get_plugin_root


async def ci_check_status(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
    wait: bool = False,
    poll_interval: int = 30,
    initial_wait: int = 60,
    max_polls: int = 40,
    wait_out_pending: bool = True,
    wait_for: list[str] | None = None,
) -> Result[dict[str, Any]]:
    script = get_plugin_root() / "skills/gh-pr-monitor/scripts/ci-check-status.py"
    args: list[str] = [
        str(script),
        "--pr",
        str(pr_number),
        "--repo",
        repo,
    ]
    if required_only:
        args.append("--required-only")
    if wait:
        args.extend(["--wait", "--poll-interval", str(poll_interval)])
        args.extend(["--initial-wait", str(initial_wait)])
        args.extend(["--max-polls", str(max_polls)])
        if not wait_out_pending:
            args.append("--no-wait-out-pending")
        for check_name in wait_for or []:
            args.extend(["--wait-for", check_name])

    timeout = float((initial_wait + poll_interval * max_polls + 60) if wait else 60)
    result = await async_run(args=args, timeout=timeout)

    if result.returncode != 0:
        return err(_script_failure(result))

    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")


def _script_failure(result: subprocess.CompletedProcess[str]) -> str:
    """A never-empty diagnostic for a failed ci-check-status run (GH-1192).

    ``ci-check-status.py`` is a stdout-parsed script, so per
    ``.claude/rules/script-domain-boundaries.md`` it emits its own
    ``{"error": ...}`` on STDOUT and exits non-zero. Reading only stderr
    therefore returned ``{"error": ""}`` — an empty string that carries
    no cause and reads as success to any caller branching on
    truthiness. Prefer the script's own message, then stderr, and fall
    back to the exit code so the payload is never empty.
    """
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    try:
        payload = json.loads(stdout) if stdout else None
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"])
    if stderr:
        return f"ci-check-status exited {result.returncode}: {stderr}"
    if stdout:
        return f"ci-check-status exited {result.returncode}: {stdout[:200]}"
    return f"ci-check-status exited {result.returncode} with no output"
