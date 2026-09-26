"""Each named step of GateResolutionQuery.run, exercised on its own (GH-1433).

The end-to-end behaviour stays pinned by ``test_gate_query.py``; these
tests prove each step holds its own guard, so a later edit to one step
is checked without routing through the other four.
"""

from __future__ import annotations

from typing import Any

import pytest

from dev10x.domain.gate_policy import BASELINE_PRESET, MIGRATOR_COMMAND
from dev10x.mcp import gate_query
from dev10x.mcp.gate_query import (
    _partition_context,
    _refuse_legacy_policy,
    _resolve_overlays,
    _resolve_session_stale,
    _resolve_supervisor_policy,
)


def _inputs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "friction_level": None,
        "walk_away": None,
        "active_modes": [],
        "gate_preset": None,
        "gate_overlays": [],
        "allowed_overlays": None,
        "supervisor_review": "none",
        "gate_overrides": {},
    }
    base.update(overrides)
    return base


class TestPartitionContext:
    def test_splits_known_fields_from_extras(self) -> None:
        accepted, ignored = _partition_context({"destructive": True, "bogus": 1, "zzz": 2})

        assert accepted == {"destructive": True}
        assert ignored == ["bogus", "zzz"]


class TestRefuseLegacyPolicy:
    def test_v2_config_is_not_refused(self) -> None:
        assert _refuse_legacy_policy(_inputs(gate_preset="adaptive")) is None

    def test_v1_config_is_refused_naming_the_migrator(self) -> None:
        refusal = _refuse_legacy_policy(_inputs(friction_level="strict"))

        assert refusal is not None
        assert MIGRATOR_COMMAND in refusal


class TestResolveOverlays:
    def test_no_posture_selects_the_baseline(self) -> None:
        preset, overlays, dropped = _resolve_overlays(_inputs(gate_overlays=["afk"]))

        assert (preset, overlays, dropped) == (BASELINE_PRESET, ["afk"], [])

    def test_allow_list_drops_unlisted_overlays(self) -> None:
        preset, overlays, dropped = _resolve_overlays(
            _inputs(
                gate_preset="adaptive",
                gate_overlays=["afk", "solo-maintainer"],
                allowed_overlays=["afk"],
            )
        )

        assert (preset, overlays, dropped) == ("adaptive", ["afk"], ["solo-maintainer"])


class TestResolveSessionStale:
    @pytest.mark.asyncio
    async def test_computes_staleness_for_session_adoption(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(gate_query, "_computed_session_stale", lambda *, toplevel: True)

        resolved = await _resolve_session_stale(
            gate="session_adoption", context={}, toplevel="/repo"
        )

        assert resolved == {"session_stale": True}

    @pytest.mark.asyncio
    async def test_keeps_a_caller_supplied_value(self) -> None:
        resolved = await _resolve_session_stale(
            gate="session_adoption", context={"session_stale": False}, toplevel="/repo"
        )

        assert resolved == {"session_stale": False}

    @pytest.mark.asyncio
    async def test_leaves_other_gates_alone(self) -> None:
        assert await _resolve_session_stale(gate="merge", context={}, toplevel="/r") == {}


class TestResolveSupervisorPolicy:
    @pytest.mark.asyncio
    async def test_overwrites_caller_supplied_facts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def never_cleared(**_: Any) -> bool:
            return False

        monkeypatch.setattr(gate_query, "_supervisor_cleared", never_cleared)

        resolved, supplied = await _resolve_supervisor_policy(
            gate="merge",
            context={"supervisor_review": "none", "supervisor_cleared": True},
            inputs=_inputs(supervisor_review="required"),
            overlays=[],
        )

        assert resolved == {"supervisor_review": "required", "supervisor_cleared": False}
        assert supplied == ["supervisor_review", "supervisor_cleared"]
