"""Tests for the resolve_gate MCP glue (ADR-0016 spike).

Covers the session.yaml → legacy mapping → resolver pipeline and the
project-tier override file, using tmp_path as the repo toplevel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.documents.session_yaml import SessionYamlDocument
from dev10x.mcp.gate_tools import (
    DOUBT_SINK_RELPATH,
    LEGACY_PROJECT_POLICY_RELPATH,
    PROJECT_POLICY_RELPATH,
    _project_overrides,
    resolve_gate_for_toplevel,
)


def _write_session_yaml(toplevel: Path, body: str) -> None:
    path = toplevel / ".claude" / "Dev10x" / "session.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _write_project_policy(toplevel: Path, body: str) -> None:
    path = toplevel / PROJECT_POLICY_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


class TestResolveGateForToplevel:
    @pytest.mark.asyncio
    async def test_adaptive_solo_maintainer_session_auto_merges(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "auto-advance"
        assert "preset:adaptive" in payload["reason"]

    @pytest.mark.asyncio
    async def test_team_repo_project_pin_stops_adaptive_merge(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "friction_level: adaptive\n")
        _write_project_policy(tmp_path, "overrides:\n  merge: ask\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "ask"

    @pytest.mark.asyncio
    async def test_session_gate_override_outranks_project_pin(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\ngate_overrides:\n  merge: auto-advance\n",
        )
        _write_project_policy(tmp_path, "overrides:\n  merge: ask\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_missing_session_yaml_defaults_to_strict_ask(self, tmp_path: Path) -> None:
        # FrictionLevel.default() is strict — the safe fallback direction.
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert "preset:strict" in payload["reason"]

    @pytest.mark.asyncio
    async def test_walk_away_maps_to_afk_overlay(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\nwalk_away: true\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="session_adoption",
            context={"session_stale": True},
            toplevel=str(tmp_path),
        )
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_bot_author_context_reaches_resolver(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "friction_level: adaptive\n")
        result = await resolve_gate_for_toplevel(
            gate="thread_resolution",
            context={"author_type": "bot", "valid_fixup_count": 1},
            toplevel=str(tmp_path),
        )
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_unknown_context_field_errors(self, tmp_path: Path) -> None:
        result = await resolve_gate_for_toplevel(
            gate="merge", context={"vibe": "good"}, toplevel=str(tmp_path)
        )
        assert "Unknown context fields" in result.to_dict()["error"]

    @pytest.mark.asyncio
    async def test_unknown_gate_errors(self, tmp_path: Path) -> None:
        result = await resolve_gate_for_toplevel(
            gate="nonsense", context={}, toplevel=str(tmp_path)
        )
        assert "Unknown gate" in result.to_dict()["error"]


class TestAllowedOverlaysGuard:
    # GH-805: a local, gitignored config.yaml ``allowed_overlays`` allow-list
    # drops disallowed high-autonomy overlays before gate resolution.

    def _write_config(self, toplevel: Path, body: str) -> None:
        path = toplevel / ".claude" / "Dev10x" / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    @pytest.mark.asyncio
    async def test_empty_allow_list_drops_solo_maintainer_overlay(self, tmp_path: Path) -> None:
        # A stale solo-maintainer overlay would skip request_review; the guard
        # drops it so the base guided preset's "ask" stands.
        self._write_config(
            tmp_path,
            "friction_level: guided\nactive_modes: [solo-maintainer]\nallowed_overlays: []\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert payload["dropped_overlays"] == ["solo-maintainer"]

    @pytest.mark.asyncio
    async def test_allow_list_keeps_named_overlay(self, tmp_path: Path) -> None:
        # solo-maintainer explicitly permitted → overlay applies (skip), no drop.
        self._write_config(
            tmp_path,
            "friction_level: guided\n"
            "active_modes: [solo-maintainer]\n"
            "allowed_overlays: [solo-maintainer]\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert payload["effect"] == "skip"
        assert "dropped_overlays" not in payload

    @pytest.mark.asyncio
    async def test_unset_allow_list_is_permissive(self, tmp_path: Path) -> None:
        # No allowed_overlays key → back-compat: overlay honored, no drop.
        self._write_config(
            tmp_path,
            "friction_level: guided\nactive_modes: [solo-maintainer]\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert payload["effect"] == "skip"
        assert "dropped_overlays" not in payload

    @pytest.mark.asyncio
    async def test_drops_afk_overlay_from_walk_away(self, tmp_path: Path) -> None:
        # afk overlay (from walk_away) also filtered by an empty allow-list.
        self._write_config(
            tmp_path,
            "friction_level: guided\nwalk_away: true\nallowed_overlays: []\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="session_adoption", context={"session_stale": True}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        # guided session_adoption is auto-advance-if-stale-free; stale → ask.
        # afk would have forced auto-advance, but it is dropped.
        assert payload["effect"] == "ask"
        assert payload["dropped_overlays"] == ["afk"]

    @pytest.mark.asyncio
    async def test_filters_explicit_new_style_gate_overlays(self, tmp_path: Path) -> None:
        # An explicit gate_overlays request is filtered too — the guard is
        # about the repo forbidding overlays regardless of how requested.
        self._write_config(
            tmp_path,
            "gate_preset: guided\ngate_overlays: [solo-maintainer]\nallowed_overlays: []\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert payload["dropped_overlays"] == ["solo-maintainer"]


class TestProjectOverrides:
    def test_missing_file_yields_no_overrides(self, tmp_path: Path) -> None:
        assert _project_overrides(str(tmp_path)) == {}

    def test_malformed_yaml_degrades_to_no_overrides(self, tmp_path: Path) -> None:
        _write_project_policy(tmp_path, ":\n  - not: [valid")
        assert _project_overrides(str(tmp_path)) == {}

    def test_non_mapping_document_degrades(self, tmp_path: Path) -> None:
        _write_project_policy(tmp_path, "- just\n- a\n- list\n")
        assert _project_overrides(str(tmp_path)) == {}

    def test_missing_overrides_key_degrades(self, tmp_path: Path) -> None:
        _write_project_policy(tmp_path, "something_else: true\n")
        assert _project_overrides(str(tmp_path)) == {}

    def test_reads_overrides_mapping(self, tmp_path: Path) -> None:
        _write_project_policy(tmp_path, "overrides:\n  merge: ask\n")
        assert _project_overrides(str(tmp_path)) == {"merge": "ask"}


class TestSessionYamlGatePolicyInputs:
    def test_reads_all_inputs(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\n"
            "active_modes: [solo-maintainer]\n"
            "walk_away: true\n"
            "gate_overrides:\n  merge: ask\n",
        )
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs == {
            "friction_level": "adaptive",
            "active_modes": ["solo-maintainer"],
            "walk_away": True,
            "gate_overrides": {"merge": "ask"},
            "gate_preset": None,
            "gate_overlays": [],
            "allowed_overlays": None,
        }

    def test_missing_file_yields_soft_defaults(self, tmp_path: Path) -> None:
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs == {
            "friction_level": "strict",
            "active_modes": [],
            "walk_away": False,
            "gate_overrides": {},
            "gate_preset": None,
            "gate_overlays": [],
            "allowed_overlays": None,
        }

    def test_reads_new_style_gate_keys(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "gate_preset: adaptive\ngate_overlays: [afk]\n",
        )
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs["gate_preset"] == "adaptive"
        assert inputs["gate_overlays"] == ["afk"]

    def test_invalid_new_style_keys_degrade(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "gate_preset: [not-a-string]\ngate_overlays: nope\n")
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs["gate_preset"] is None
        assert inputs["gate_overlays"] == []

    def test_invalid_shapes_degrade(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "active_modes: not-a-list\ngate_overrides: not-a-mapping\n",
        )
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs["active_modes"] == []
        assert inputs["gate_overrides"] == {}


class TestNewStylePresetResolution:
    # ADR-0016 #753: gate_preset/gate_overlays win over the legacy mapping.

    @pytest.mark.asyncio
    async def test_gate_preset_key_drives_resolution(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "gate_preset: strict\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert "preset:strict" in payload["reason"]

    @pytest.mark.asyncio
    async def test_gate_overlays_apply_over_new_preset(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "gate_preset: guided\ngate_overlays: [solo-maintainer]\n")
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        # guided asks for request_review; the solo-maintainer overlay skips it.
        assert result.to_dict()["effect"] == "skip"

    @pytest.mark.asyncio
    async def test_new_style_preset_outranks_legacy_keys(self, tmp_path: Path) -> None:
        # Both shapes present — the new-style gate_preset wins (D-4).
        _write_session_yaml(tmp_path, "friction_level: strict\ngate_preset: adaptive\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_gate_preset_inherits_legacy_overlays_when_gate_overlays_absent(
        self, tmp_path: Path
    ) -> None:
        # Round 1 review C3: a transition file (gate_preset + legacy
        # active_modes, no gate_overlays) must NOT silently drop the
        # solo-maintainer overlay — request_review stays skipped.
        _write_session_yaml(
            tmp_path,
            "gate_preset: guided\nactive_modes: [solo-maintainer]\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        assert result.to_dict()["effect"] == "skip"


class TestDurableProjectPin:
    # ADR-0016 #752: durable git-tracked pin with legacy fallback.

    def test_prefers_durable_path(self, tmp_path: Path) -> None:
        (tmp_path / PROJECT_POLICY_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / PROJECT_POLICY_RELPATH).write_text("overrides:\n  merge: ask\n")
        assert _project_overrides(str(tmp_path)) == {"merge": "ask"}

    def test_falls_back_to_legacy_path(self, tmp_path: Path) -> None:
        (tmp_path / LEGACY_PROJECT_POLICY_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / LEGACY_PROJECT_POLICY_RELPATH).write_text("overrides:\n  merge: ask\n")
        assert _project_overrides(str(tmp_path)) == {"merge": "ask"}

    def test_durable_path_wins_over_legacy(self, tmp_path: Path) -> None:
        (tmp_path / PROJECT_POLICY_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / PROJECT_POLICY_RELPATH).write_text("overrides:\n  merge: auto-advance\n")
        (tmp_path / LEGACY_PROJECT_POLICY_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / LEGACY_PROJECT_POLICY_RELPATH).write_text("overrides:\n  merge: ask\n")
        assert _project_overrides(str(tmp_path)) == {"merge": "auto-advance"}


class TestSessionAdoptionStaleness:
    # ADR-0016 #753 / GH-742 F1: session_adoption keys on computed staleness.

    @pytest.mark.asyncio
    async def test_missing_identity_is_stale_and_asks(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "gate_preset: adaptive\n")
        result = await resolve_gate_for_toplevel(
            gate="session_adoption", context={}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert "stale=true" in payload["reason"]

    @pytest.mark.asyncio
    async def test_explicit_session_stale_context_is_respected(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "gate_preset: adaptive\n")
        result = await resolve_gate_for_toplevel(
            gate="session_adoption",
            context={"session_stale": False},
            toplevel=str(tmp_path),
        )
        assert result.to_dict()["effect"] == "auto-advance"


class TestAutoAdvanceRecordEmission:
    # ADR-0016 #754 / D-7: auto-advances surface + persist a visible record.

    @pytest.mark.asyncio
    async def test_auto_advance_payload_carries_record_and_writes_sink(
        self, tmp_path: Path
    ) -> None:
        _write_session_yaml(tmp_path, "gate_preset: adaptive\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "auto-advance"
        assert payload["record"].startswith("⚙ gate:merge auto-advance")
        sink = tmp_path / DOUBT_SINK_RELPATH
        assert sink.exists()
        assert "gate:merge auto-advance" in sink.read_text()

    @pytest.mark.asyncio
    async def test_ask_resolution_emits_no_record(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "gate_preset: strict\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert "record" not in payload
        assert not (tmp_path / DOUBT_SINK_RELPATH).exists()

    @pytest.mark.asyncio
    async def test_missing_shipped_yaml_falls_back_to_domain_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # presets/friction/ absent at runtime → empty load → domain default.
        import dev10x.config.friction_presets as fp

        monkeypatch.setattr(fp, "load_shipped_presets", lambda: {})
        monkeypatch.setattr(fp, "load_shipped_overlays", lambda: {})
        _write_session_yaml(tmp_path, "gate_preset: adaptive\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_sink_write_failure_is_swallowed(self, tmp_path: Path) -> None:
        # The doubt_sink write is best-effort — an OSError must not break
        # the resolution (the record still returns in the payload).
        _write_session_yaml(tmp_path, "gate_preset: adaptive\n")
        sink = tmp_path / DOUBT_SINK_RELPATH
        sink.parent.mkdir(parents=True, exist_ok=True)
        sink.mkdir()  # a directory where the record file goes → append raises
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "auto-advance"
        assert payload["record"].startswith("⚙ gate:merge auto-advance")
