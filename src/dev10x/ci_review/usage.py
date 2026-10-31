from __future__ import annotations

import math
from typing import Any

NOTIONAL_SUFFIX: str = " (notional — OAuth subscription)"


def usage_report(*, execution: list[dict[str, Any]], notional: bool) -> str:
    results = [message for message in execution if message.get("type") == "result"]
    result: dict[str, Any] = results[-1] if results else {}
    models: dict[str, dict[str, Any]] = result.get("modelUsage") or {}
    suffix = NOTIONAL_SUFFIX if notional else ""
    rows = "\n".join(
        f"| {model} | {usage.get('inputTokens') or 0}"
        f" | {usage.get('cacheCreationInputTokens') or 0}"
        f" | {usage.get('cacheReadInputTokens') or 0}"
        f" | {usage.get('outputTokens') or 0}"
        f" | {_jq_number(value=_round(value=usage.get('costUSD') or 0, places=4))} |"
        for model, usage in models.items()
    )
    total = result.get("total_cost_usd") or 0
    turns = result.get("num_turns") or 0
    denials = len(result.get("permission_denials") or [])
    table = (
        "### Claude usage\n\n"
        "| Model | Input | Cache write | Cache read | Output | Cost (USD) |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        f"{rows}\n\n"
        f"**Total:** ${_jq_number(value=_round(value=total, places=2))} · {turns} turns"
        f" · {denials} permission denials{suffix}\n"
    )
    cache_read = sum(usage.get("cacheReadInputTokens") or 0 for usage in models.values())
    cache_write = sum(usage.get("cacheCreationInputTokens") or 0 for usage in models.values())
    uncached = sum(usage.get("inputTokens") or 0 for usage in models.values())
    notice = (
        f"::notice title=Claude usage::${_jq_number(value=total)} · {turns} turns"
        f" · cache read {cache_read} · cache write {cache_write}"
        f" · uncached input {uncached}{suffix}"
    )
    return f"{table}\n{notice}\n"


def _round(*, value: float, places: int) -> float:
    # jq's `round` goes half away from zero; Python's round() is banker's.
    scale = 10**places
    return math.copysign(math.floor(abs(value) * scale + 0.5), value) / scale


def _jq_number(*, value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))
