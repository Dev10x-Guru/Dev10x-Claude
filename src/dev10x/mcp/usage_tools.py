"""Usage-block MCP tool registration (GH-878).

Exposes offline Claude Code usage reporting so agents can check the active
5-hour block's token/cost budget with zero Bash-layer friction — replacing
the un-allow-listable `npx --yes ccusage@latest blocks --active --json`
package-runner call. See tracker #796.
"""

from __future__ import annotations

from dev10x.domain.common.result import to_wire
from dev10x.domain.usage import blocks_report
from dev10x.mcp._app import server


@server.tool()
async def usage_blocks(active: bool = True) -> dict:
    """Report Claude Code usage blocks read offline from local session data.

    Reads ~/.claude usage JSONL and a bundled offline pricing table — never
    fetches. Mirrors `ccusage blocks --active --json`. Cost is an offline
    estimate; token counts are read verbatim.

    Args:
        active: When True (default), return only the active 5-hour block.

    Returns:
        Dictionary with keys: blocks (list), pricingSource, unpricedModels.
        Each block carries id, startTime, endTime, actualEndTime, isActive,
        entries, tokenCounts, totalTokens, costUSD, models, elapsedMinutes,
        remainingMinutes, burnRate, projection.
    """
    return to_wire(blocks_report(active_only=active))
