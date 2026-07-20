"""Tests for the service-layer GateResolutionQuery (GH-840).

The read+compute half of gate resolution now lives in a query object that
returns an assembled GateContext + resolution, testable without the MCP
adapter's side effects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.common.result import ErrorResult
from dev10x.domain.gate_policy import GateContext
from dev10x.mcp.gate_query import GateResolutionOutcome, GateResolutionQuery


def _write_config(toplevel: Path, body: str) -> None:
    # Durable keys (friction_level / active_modes / allowed_overlays) are read
    # from the gitignored config.yaml, not session.yaml (GH-805).
    path = toplevel / ".claude" / "Dev10x" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


class TestGateResolutionQuery:
    @pytest.mark.asyncio
    async def test_returns_outcome_with_assembled_context(self, tmp_path: Path) -> None:
        result = await GateResolutionQuery(gate="merge", context={}, toplevel=str(tmp_path)).run()
        assert not isinstance(result, ErrorResult)
        outcome = result.value
        assert isinstance(outcome, GateResolutionOutcome)
        assert isinstance(outcome.context, GateContext)
        assert outcome.resolution.gate == "merge"
        assert outcome.dropped_overlays == []

    @pytest.mark.asyncio
    async def test_unknown_context_field_ignored_not_errored(self, tmp_path: Path) -> None:
        # GH-854 F1: an unknown context key is dropped and surfaced, not
        # hard-failed — the gate still resolves on the remaining facts.
        result = await GateResolutionQuery(
            gate="merge", context={"vibe": "good"}, toplevel=str(tmp_path)
        ).run()
        assert not isinstance(result, ErrorResult)
        assert result.value.ignored_context_fields == ["vibe"]
        assert result.value.resolution.gate == "merge"

    @pytest.mark.asyncio
    async def test_known_and_unknown_fields_partitioned(self, tmp_path: Path) -> None:
        # A valid field is kept and applied; only the unknown one is dropped.
        result = await GateResolutionQuery(
            gate="batch_layout",
            context={"overlap_signals": 2, "typo_field": 1},
            toplevel=str(tmp_path),
        ).run()
        assert not isinstance(result, ErrorResult)
        assert result.value.ignored_context_fields == ["typo_field"]
        assert result.value.context.overlap_signals == 2

    @pytest.mark.asyncio
    async def test_session_adoption_computes_stale_onto_context(self, tmp_path: Path) -> None:
        # No explicit session_stale → the branch-only fallback is computed
        # and lands on the assembled context.
        result = await GateResolutionQuery(
            gate="session_adoption", context={}, toplevel=str(tmp_path)
        ).run()
        assert not isinstance(result, ErrorResult)
        assert isinstance(result.value.context.session_stale, bool)

    @pytest.mark.asyncio
    async def test_disallowed_overlay_is_dropped(self, tmp_path: Path) -> None:
        # allowed_overlays acts as an allow-list: solo-maintainer is not on it,
        # so the durable-mode guard drops it before resolution (GH-805).
        _write_config(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\nallowed_overlays: [afk]\n",
        )
        result = await GateResolutionQuery(gate="merge", context={}, toplevel=str(tmp_path)).run()
        assert not isinstance(result, ErrorResult)
        assert "solo-maintainer" in result.value.dropped_overlays
