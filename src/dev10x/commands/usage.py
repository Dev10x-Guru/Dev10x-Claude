from __future__ import annotations

import json
import sys
from typing import Any

import click

from dev10x.domain.common.result import ErrorResult


@click.group()
def usage() -> None:
    """Report Claude Code usage read offline from local session data.

    Offline replacement for `npx ccusage blocks` — reads the local
    ~/.claude usage JSONL, never fetches. See GH-878.
    """


@usage.command(name="blocks")
@click.option(
    "--active/--all",
    "active_only",
    default=False,
    help="Show only the active 5-hour block (default: all blocks).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON (ccusage-compatible shape).")
def blocks(*, active_only: bool, as_json: bool) -> None:
    """Report 5-hour usage blocks (start/end, tokens, estimated cost).

    Cost is an OFFLINE estimate derived from token counts; the token
    counts themselves are read verbatim from the session logs.
    """
    from dev10x.domain.usage import blocks_report

    result = blocks_report(active_only=active_only)
    if isinstance(result, ErrorResult):
        click.echo(f"❌ {result.error}", err=True)
        sys.exit(1)

    report = result.value
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return

    _print_summary(report)


def _print_summary(report: dict[str, Any]) -> None:
    block_list: list[dict[str, Any]] = report.get("blocks", [])
    if not block_list:
        click.echo("No usage blocks found.")
        return
    for block in block_list:
        counts = block["tokenCounts"]
        marker = "● active" if block["isActive"] else "  closed"
        click.echo(f"{marker}  {block['startTime']} → {block['endTime']}")
        click.echo(
            "  tokens:"
            f" in={counts['inputTokens']:,}"
            f" out={counts['outputTokens']:,}"
            f" cache_write={counts['cacheCreationInputTokens']:,}"
            f" cache_read={counts['cacheReadInputTokens']:,}"
            f" total={block['totalTokens']:,}"
        )
        click.echo(
            f"  cost≈${block['costUSD']:.4f} (offline estimate)"
            f"  elapsed={block['elapsedMinutes']}m"
            f"  remaining={block['remainingMinutes']}m"
        )
    if report.get("unpricedModels"):
        click.echo(f"  unpriced models (cost excluded): {', '.join(report['unpricedModels'])}")
