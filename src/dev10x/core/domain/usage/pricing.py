"""Offline pricing table for usage-block cost estimation (GH-878).

`dev10x usage blocks` reports the active 5-hour usage block **offline** —
it never fetches LiteLLM/remote pricing. Claude Code's usage JSONL only
carries a `costUSD` field intermittently (usually `null`), so the block's
cost is estimated from the token counts and this bundled table.

[Verify] The per-model rates below are an offline estimate and may drift
as published pricing changes. The exact, authoritative signal a caller
should trust is the token counts (`tokenCounts`), which are read verbatim
from the JSONL; `costUSD` is a best-effort derived value. A model with no
matching entry contributes zero cost and is surfaced under
``unpricedModels`` so callers can tell "cheap" from "unpriced".

Rates are USD per **million** tokens (MTok). Cache-write is charged at the
5-minute-TTL rate (1.25x input) as a single blended rate — the JSONL does
not always separate 5m vs 1h cache-creation cleanly. Cache-read is the
discounted rate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRates:
    """USD-per-million-token rates for one model family."""

    input: float
    output: float
    cache_write: float
    cache_read: float


# Keyed by a lowercase substring matched against the model id (first hit
# wins, longest key first). [Verify] — offline estimate, see module docstring.
_RATES: dict[str, ModelRates] = {
    "opus": ModelRates(input=15.0, output=75.0, cache_write=18.75, cache_read=1.5),
    "sonnet": ModelRates(input=3.0, output=15.0, cache_write=3.75, cache_read=0.3),
    "haiku": ModelRates(input=1.0, output=5.0, cache_write=1.25, cache_read=0.1),
}

_PER_MILLION = 1_000_000.0


def rates_for(model: str) -> ModelRates | None:
    """Return the rate card for a model id, or None when unpriced.

    Matches the longest known family substring first so a more specific
    family would win over a broader one if they overlapped.
    """
    lowered = model.lower()
    for family in sorted(_RATES, key=len, reverse=True):
        if family in lowered:
            return _RATES[family]
    return None


def estimate_cost(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
) -> float | None:
    """Estimate one record's cost in USD, or None when the model is unpriced.

    None (not 0.0) signals "no rate card" so the caller can distinguish an
    unpriced model from a genuinely zero-cost record.
    """
    rates = rates_for(model)
    if rates is None:
        return None
    return (
        input_tokens * rates.input
        + output_tokens * rates.output
        + cache_creation_input_tokens * rates.cache_write
        + cache_read_input_tokens * rates.cache_read
    ) / _PER_MILLION


__all__ = ["ModelRates", "rates_for", "estimate_cost"]
