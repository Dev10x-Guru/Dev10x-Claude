"""CI monitoring MCP tool implementations.

Wraps ci-check-status operations as MCP tools so skills can
check CI status without Bash allow-rule friction.
"""

from __future__ import annotations

import json
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

    timeout = float((initial_wait + poll_interval * max_polls + 60) if wait else 60)
    result = await async_run(args=args, timeout=timeout)

    if result.returncode != 0:
        return err(result.stderr.strip())

    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
