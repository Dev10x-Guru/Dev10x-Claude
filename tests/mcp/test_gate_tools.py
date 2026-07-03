"""Tests for the resolve_gate MCP glue (ADR-0016 spike).

Covers the session.yaml → legacy mapping → resolver pipeline and the
project-tier override file, using tmp_path as the repo toplevel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.documents.session_yaml import SessionYamlDocument
from dev10x.mcp.gate_tools import (
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
        assert payload["effect"] == "auto"
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
            "friction_level: adaptive\ngate_overrides:\n  merge: auto\n",
        )
        _write_project_policy(tmp_path, "overrides:\n  merge: ask\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "auto"

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
        assert result.to_dict()["effect"] == "auto"

    @pytest.mark.asyncio
    async def test_bot_author_context_reaches_resolver(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "friction_level: adaptive\n")
        result = await resolve_gate_for_toplevel(
            gate="thread_resolution",
            context={"author_type": "bot", "valid_fixup_count": 1},
            toplevel=str(tmp_path),
        )
        assert result.to_dict()["effect"] == "auto"

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
        }

    def test_missing_file_yields_soft_defaults(self, tmp_path: Path) -> None:
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs == {
            "friction_level": "strict",
            "active_modes": [],
            "walk_away": False,
            "gate_overrides": {},
        }

    def test_invalid_shapes_degrade(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "active_modes: not-a-list\ngate_overrides: not-a-mapping\n",
        )
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs["active_modes"] == []
        assert inputs["gate_overrides"] == {}
