"""Strategy registry for Dev10x:plugin-doctor (GH-87).

The registry knows how to load shipped strategies (plus optional
user-defined strategies under
``~/.claude/Dev10x/doctor/strategies/``). Loading is explicit —
no module-level discovery — so a misconfigured user strategy
cannot break the doctor at import time.
"""

from __future__ import annotations

from importlib import import_module

from dev10x.skills.doctor.strategy import Strategy

DEFAULT_STRATEGY_MODULES: tuple[str, ...] = (
    "dev10x.skills.doctor.strategies.mcp_vs_script_drift",
    "dev10x.skills.doctor.strategies.missing_linear_mcp_allow",
)


def load_strategies(*, module_paths: tuple[str, ...] | None = None) -> list[Strategy]:
    """Import each module path and collect its ``STRATEGY`` constant.

    Strategies missing the ``STRATEGY`` attribute are skipped silently;
    import errors propagate so the user sees the underlying problem
    instead of a degraded doctor run.
    """
    paths = module_paths if module_paths is not None else DEFAULT_STRATEGY_MODULES
    strategies: list[Strategy] = []
    for module_path in paths:
        module = import_module(module_path)
        strategy = getattr(module, "STRATEGY", None)
        if isinstance(strategy, Strategy):
            strategies.append(strategy)
    return strategies
