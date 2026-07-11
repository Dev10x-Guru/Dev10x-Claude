"""Strategy registry for Dev10x:plugin-doctor (GH-87).

``load_strategies`` is a **Plugin loader** (Fowler PoEAA): module
paths act as configuration and each module is bound late, collecting
its ``STRATEGY`` constant. It composes the shared
:class:`dev10x.domain.common.plugin_loader.PluginLoader` — the same
utility ``dev10x.validators.registry`` uses (#844) — in its *lenient*
posture: a module missing (or mistyping) ``STRATEGY`` is skipped so a
misconfigured user strategy cannot break the doctor at import time.

The registry knows how to load shipped strategies (plus optional
user-defined strategies under
``~/.claude/Dev10x/doctor/strategies/``). Loading is explicit —
no module-level discovery.
"""

from __future__ import annotations

from dev10x.domain.common.plugin_loader import PluginLoader
from dev10x.skills.doctor.strategy import StrategyProtocol

DEFAULT_STRATEGY_MODULES: tuple[str, ...] = (
    "dev10x.skills.doctor.strategies.mcp_vs_script_drift",
    "dev10x.skills.doctor.strategies.missing_linear_mcp_allow",
    "dev10x.skills.doctor.strategies.forbidden_token_priming",
    "dev10x.skills.doctor.strategies.mcp_horizontal_duplicates",
)

_STRATEGY_MARKER = "STRATEGY"
# StrategyProtocol is a runtime_checkable Protocol (isinstance works at
# runtime); mypy still rejects a Protocol where a concrete type[T] is
# expected, so the type-abstract check is suppressed here only.
_loader: PluginLoader[StrategyProtocol] = PluginLoader(
    protocol=StrategyProtocol  # type: ignore[type-abstract]
)


def load_strategies(*, module_paths: tuple[str, ...] | None = None) -> list[StrategyProtocol]:
    """Import each module path and collect its ``STRATEGY`` constant.

    Strategies missing the ``STRATEGY`` attribute are skipped silently;
    import errors propagate so the user sees the underlying problem
    instead of a degraded doctor run.
    """
    paths = module_paths if module_paths is not None else DEFAULT_STRATEGY_MODULES
    return _loader.collect((path, _STRATEGY_MARKER) for path in paths)
