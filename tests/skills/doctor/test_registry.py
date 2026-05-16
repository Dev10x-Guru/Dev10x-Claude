"""Tests for Dev10x:doctor strategy registry (GH-87)."""

from __future__ import annotations

import pytest

registry = pytest.importorskip(
    "dev10x.skills.doctor.registry",
    reason="dev10x not installed",
)
from dev10x.skills.doctor.strategy import Strategy  # noqa: E402


class TestLoadStrategies:
    def test_default_set_includes_mcp_vs_script_drift(self) -> None:
        strategies = registry.load_strategies()

        ids = [s.id for s in strategies]
        assert "mcp-vs-script-drift" in ids

    def test_returns_strategy_instances(self) -> None:
        strategies = registry.load_strategies()

        for strategy in strategies:
            assert isinstance(strategy, Strategy)
            assert callable(strategy.detect)
            assert callable(strategy.remediate)

    def test_module_without_strategy_constant_is_skipped(self) -> None:
        result = registry.load_strategies(module_paths=("dev10x.skills.doctor.strategy",))
        assert result == []
