"""Release notes MCP tool implementations.

Wraps collect-prs.py as an MCP tool so the release-notes skill
can collect PR data without Bash allow-rule friction.
"""

from __future__ import annotations

from typing import Any

from dev10x.subprocess_utils import async_run, get_plugin_root


async def collect_prs(
    *,
    repo_path: str,
    from_tag: str | None = None,
    to_tag: str | None = None,
    ticket_pattern: str | None = None,
) -> dict[str, Any]:
    script = get_plugin_root() / "skills/release-notes/scripts/collect-prs.py"
    args: list[str] = [str(script), repo_path]

    if from_tag:
        args.extend(["--from", from_tag])
    if to_tag:
        args.extend(["--to", to_tag])
    if ticket_pattern:
        args.extend(["--ticket-pattern", ticket_pattern])

    result = await async_run(args=args, timeout=120)

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return {"success": True, "output": result.stdout.strip()}
