"""Audit-record summarization (audit finding D4).

Aggregating raw audit records into per-hook statistics is a distinct
concern from reading/appending the JSONL log. It lived in
``audit.log_reader`` only because that was the first home; this module
owns it now so the reader stays focused on log IO. ``log_reader`` keeps
a re-export of :func:`summarize` for the existing import path.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.hook_telemetry import HookOutcome, HookPhase


def summarize(*, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate records by hook name. Joins wrap+body via span_id when both
    records are present.
    """
    by_span: dict[str, dict[str, Any]] = {}
    body_only: list[dict[str, Any]] = []
    wrap_only: list[dict[str, Any]] = []

    for rec in records:
        phase = rec.get("phase")
        span_id = rec.get("span_id", "")
        if not span_id:
            if phase == HookPhase.BODY:
                body_only.append(rec)
            elif phase == HookPhase.WRAP:
                wrap_only.append(rec)
            continue
        if not isinstance(phase, str):
            continue
        bucket = by_span.setdefault(span_id, {})
        bucket[phase] = rec

    hook_stats: dict[str, dict[str, Any]] = {}
    for span in by_span.values():
        body = span.get(HookPhase.BODY)
        wrap = span.get(HookPhase.WRAP)
        record = body or wrap
        if record is None:
            continue
        hook = record.get("hook", "unknown")
        stats = hook_stats.setdefault(
            hook,
            {
                "count": 0,
                "total_ms_sum": 0,
                "body_ms_sum": 0,
                "startup_ms_sum": 0,
                "paired_count": 0,
                "error_count": 0,
                "block_count": 0,
            },
        )
        stats["count"] += 1
        outcome = record.get("outcome", "")
        if outcome == HookOutcome.ERROR:
            stats["error_count"] += 1
        elif outcome == HookOutcome.BLOCK:
            stats["block_count"] += 1
        if body and wrap:
            total = int(wrap.get("total_ms") or 0)
            body_ms = int(body.get("body_ms") or 0)
            stats["total_ms_sum"] += total
            stats["body_ms_sum"] += body_ms
            stats["startup_ms_sum"] += max(total - body_ms, 0)
            stats["paired_count"] += 1

    for stats in hook_stats.values():
        paired = stats["paired_count"] or 1
        stats["total_ms_avg"] = round(stats["total_ms_sum"] / paired, 1)
        stats["body_ms_avg"] = round(stats["body_ms_sum"] / paired, 1)
        stats["startup_ms_avg"] = round(stats["startup_ms_sum"] / paired, 1)

    return hook_stats
