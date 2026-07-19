from __future__ import annotations

import pytest

from dev10x.domain.usage import pricing


@pytest.mark.parametrize(
    "model,family_input_rate",
    [
        ("claude-opus-4-8", 15.0),
        ("claude-sonnet-5", 3.0),
        ("claude-haiku-4-5-20251001", 1.0),
    ],
)
def test_rates_for_known_families(model: str, family_input_rate: float) -> None:
    rates = pricing.rates_for(model)
    assert rates is not None
    assert rates.input == family_input_rate


def test_rates_for_unknown_returns_none() -> None:
    assert pricing.rates_for("claude-fable-5") is None


def test_estimate_cost_known_model() -> None:
    # opus: (1_000_000*15 + 1_000_000*75 + 1_000_000*18.75 + 1_000_000*1.5) / 1e6
    cost = pricing.estimate_cost(
        model="claude-opus-4-8",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    assert cost == pytest.approx(15.0 + 75.0 + 18.75 + 1.5)


def test_estimate_cost_unknown_model_is_none() -> None:
    assert (
        pricing.estimate_cost(
            model="claude-fable-5",
            input_tokens=100,
            output_tokens=100,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        is None
    )
