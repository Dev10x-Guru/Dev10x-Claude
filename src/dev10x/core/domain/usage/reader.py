"""Offline reader for Claude Code usage blocks (GH-878).

Reads Claude Code's local session transcripts under ``~/.claude/projects``
(``ClaudeDir.projects_dir()``, override via ``DEV10X_CLAUDE_HOME``), extracts
the per-message token usage, buckets it into 5-hour "blocks" the same way
``ccusage`` does, and reports the active block — entirely offline, no network.

This retires the ``npx --yes ccusage@latest blocks --active --json --offline``
call that hard-prompts on every worktree and cannot be safely allow-listed
(a remote package runner). See GH-878 / tracker #796.

The output shape mirrors ``ccusage blocks --active --json`` so a caller that
already parses that surface migrates as a drop-in. Extra convenience keys
(``elapsedMinutes`` / ``remainingMinutes``) are additive.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.result import Result, ok
from dev10x.domain.usage.pricing import estimate_cost

log = logging.getLogger(__name__)

SESSION_DURATION = timedelta(hours=5)
PRICING_SOURCE = "offline-estimate"


@dataclass(frozen=True)
class UsageEntry:
    timestamp: datetime
    request_id: str | None
    message_id: str | None
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float | None


@dataclass
class UsageBlock:
    start: datetime
    entries: list[UsageEntry] = field(default_factory=list)


def parse_entry(record: dict[str, Any]) -> UsageEntry | None:
    """Parse one JSONL record into a UsageEntry, or None when it carries no usage."""
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    raw_ts = record.get("timestamp")
    if not isinstance(raw_ts, str):
        return None
    try:
        timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    model = str(message.get("model") or "unknown")
    # Synthetic messages (injected by the harness) are not real API usage —
    # ccusage excludes them; matching that keeps token/cost totals accurate.
    if model == "<synthetic>":
        return None
    cost = record.get("costUSD")
    return UsageEntry(
        timestamp=timestamp,
        request_id=record.get("requestId"),
        message_id=message.get("id"),
        model=model,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
    )


def iter_entries(projects_dir: Path) -> Iterator[UsageEntry]:
    """Yield every usage entry from all JSONL transcripts, skipping bad lines."""
    if not projects_dir.is_dir():
        return
    for path in sorted(projects_dir.rglob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as ex:
            log.warning("usage: cannot read %s: %s", path, ex)
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                entry = parse_entry(record)
                if entry is not None:
                    yield entry


def _dedup(entries: list[UsageEntry]) -> list[UsageEntry]:
    """Drop duplicate records keyed by (message_id, request_id) when identifiable."""
    seen: set[tuple[str, str]] = set()
    result: list[UsageEntry] = []
    for entry in entries:
        if entry.message_id and entry.request_id:
            key = (entry.message_id, entry.request_id)
            if key in seen:
                continue
            seen.add(key)
        result.append(entry)
    return result


def _floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def build_blocks(entries: list[UsageEntry]) -> list[UsageBlock]:
    """Bucket time-sorted entries into 5-hour blocks (ccusage semantics)."""
    ordered = sorted(_dedup(entries), key=lambda e: e.timestamp)
    blocks: list[UsageBlock] = []
    current: UsageBlock | None = None
    for entry in ordered:
        if current is None:
            current = UsageBlock(start=_floor_hour(entry.timestamp))
        else:
            since_start = entry.timestamp - current.start
            since_last = entry.timestamp - current.entries[-1].timestamp
            if since_start >= SESSION_DURATION or since_last >= SESSION_DURATION:
                blocks.append(current)
                current = UsageBlock(start=_floor_hour(entry.timestamp))
        current.entries.append(entry)
    if current is not None:
        blocks.append(current)
    return blocks


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def is_active(block: UsageBlock, now: datetime) -> bool:
    # A block is active while `now` is within its 5-hour window. build_blocks
    # guarantees every entry sits within 5h of `start`, so the last entry is
    # always before `end_time` — no separate "stale last entry" check needed.
    return now < block.start + SESSION_DURATION


def _block_cost(block: UsageBlock, unpriced: set[str]) -> float:
    total = 0.0
    for entry in block.entries:
        if entry.cost_usd is not None:
            total += entry.cost_usd
            continue
        estimate = estimate_cost(
            model=entry.model,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            cache_creation_input_tokens=entry.cache_creation_input_tokens,
            cache_read_input_tokens=entry.cache_read_input_tokens,
        )
        if estimate is None:
            unpriced.add(entry.model)
        else:
            total += estimate
    return total


def _serialize_block(
    block: UsageBlock,
    now: datetime,
    unpriced: set[str],
) -> dict[str, Any]:
    end_time = block.start + SESSION_DURATION
    last_ts = block.entries[-1].timestamp
    active = is_active(block, now)

    input_tokens = sum(e.input_tokens for e in block.entries)
    output_tokens = sum(e.output_tokens for e in block.entries)
    cache_creation = sum(e.cache_creation_input_tokens for e in block.entries)
    cache_read = sum(e.cache_read_input_tokens for e in block.entries)
    total_tokens = input_tokens + output_tokens + cache_creation + cache_read
    cost = _block_cost(block, unpriced)

    reference_end = now if active else last_ts
    elapsed_minutes = max(0, int((reference_end - block.start).total_seconds() // 60))
    remaining_minutes = max(0, int((end_time - now).total_seconds() // 60)) if active else 0

    payload: dict[str, Any] = {
        "id": _iso(block.start),
        "startTime": _iso(block.start),
        "endTime": _iso(end_time),
        "actualEndTime": _iso(last_ts),
        "isActive": active,
        "isGap": False,
        "entries": len(block.entries),
        "tokenCounts": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheCreationInputTokens": cache_creation,
            "cacheReadInputTokens": cache_read,
        },
        "totalTokens": total_tokens,
        "costUSD": round(cost, 6),
        "models": sorted({e.model for e in block.entries}),
        "elapsedMinutes": elapsed_minutes,
        "remainingMinutes": remaining_minutes,
        "burnRate": None,
        "projection": None,
    }

    if active and elapsed_minutes > 0:
        tokens_per_minute = total_tokens / elapsed_minutes
        cost_per_hour = cost / elapsed_minutes * 60
        payload["burnRate"] = {
            "tokensPerMinute": round(tokens_per_minute, 2),
            "costPerHour": round(cost_per_hour, 4),
        }
        payload["projection"] = {
            "totalTokens": int(total_tokens + tokens_per_minute * remaining_minutes),
            "totalCost": round(cost + cost_per_hour / 60 * remaining_minutes, 4),
            "remainingMinutes": remaining_minutes,
        }
    return payload


def blocks_report(
    *,
    active_only: bool = True,
    now: datetime | None = None,
    projects_dir: Path | None = None,
) -> Result[dict[str, Any]]:
    """Report usage blocks read offline from local Claude Code transcripts.

    Args:
        active_only: When True, return only the active 5-hour block (0 or 1).
        now: Reference time (defaults to current UTC). Injectable for tests.
        projects_dir: Transcript root (defaults to ClaudeDir.projects_dir()).

    Returns:
        ok({"blocks": [...], "pricingSource": ..., "unpricedModels": [...]}).
        An absent transcript directory yields an empty block list, not an
        error — "no usage yet" is a valid state.
    """
    moment = now or datetime.now(UTC)
    root = projects_dir or ClaudeDir.projects_dir()

    blocks = build_blocks(list(iter_entries(root)))
    if active_only:
        blocks = [b for b in blocks if is_active(b, moment)]

    unpriced: set[str] = set()
    serialized = [_serialize_block(b, moment, unpriced) for b in blocks]

    return ok(
        {
            "blocks": serialized,
            "pricingSource": PRICING_SOURCE,
            "unpricedModels": sorted(unpriced),
        }
    )


__all__ = [
    "UsageEntry",
    "UsageBlock",
    "SESSION_DURATION",
    "PRICING_SOURCE",
    "parse_entry",
    "iter_entries",
    "build_blocks",
    "is_active",
    "blocks_report",
]
