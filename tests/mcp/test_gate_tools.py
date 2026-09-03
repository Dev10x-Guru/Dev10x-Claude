"""Tests for the resolve_gate MCP glue (ADR-0016 spike).

Covers the session.yaml → legacy mapping → resolver pipeline and the
project-tier override file, using tmp_path as the repo toplevel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.documents.session_yaml import SessionYamlDocument
from dev10x.mcp.gate_query import (
    LEGACY_PROJECT_POLICY_RELPATH,
    PROJECT_POLICY_RELPATH,
    _project_overrides,
)
from dev10x.mcp.gate_tools import (
    DOUBT_SINK_RELPATH,
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
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\nhuman_review: false\n",
        )
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "auto-advance"
        assert "preset:adaptive" in payload["reason"]

    @pytest.mark.asyncio
    async def test_legacy_human_review_key_still_floors_the_merge_gate(
        self, tmp_path: Path
    ) -> None:
        # ADR-0019 behaviour 3 (GH-1000), renamed by ADR-0022 D-2: the
        # precondition is read from the durable prefs by the query itself, so
        # a caller that passes no context still gets the repo's review
        # posture applied — and the deprecated `human_review: true` spelling
        # still resolves to `supervisor_review: required` (GH-1161).
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\nhuman_review: true\n",
        )
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert "supervisor_review" in payload["floors_applied"]

    @pytest.mark.asyncio
    async def test_explicit_supervisor_review_floors_the_merge_gate(self, tmp_path: Path) -> None:
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\n"
            "supervisor_review: required\n",
        )
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "ask"

    @pytest.mark.asyncio
    async def test_explicit_key_outranks_the_deprecated_alias(self, tmp_path: Path) -> None:
        # Both spellings present: the new key wins, so a half-migrated file
        # does not silently keep the old answer.
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\n"
            "human_review: true\nsupervisor_review: none\n",
        )
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_unset_review_posture_floors_the_merge_gate(self, tmp_path: Path) -> None:
        # Absent key reads as `required` — an unconfigured repo keeps a human
        # on the merge rather than inheriting the preset's autonomy.
        _write_session_yaml(
            tmp_path, "friction_level: adaptive\nactive_modes: [solo-maintainer]\n"
        )
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "ask"

    @pytest.mark.asyncio
    async def test_caller_cannot_lift_the_floor_by_supplying_the_posture(
        self, tmp_path: Path
    ) -> None:
        # NOT the session_stale seam: the review posture is durable project
        # policy, not a per-instance fact. Honouring the caller here would
        # let any resolve_gate caller clear the floor with one wire key,
        # leaving the "structural precondition" convention-deep at the
        # boundary meant to enforce it. Both the current key and the retired
        # alias are inert on the wire.
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\n"
            "supervisor_review: required\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="merge",
            context={"human_review": False, "supervisor_review": "none"},
            toplevel=str(tmp_path),
        )
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert "supervisor_review" in payload["floors_applied"]
        assert payload["ignored_context_fields"] == ["human_review", "supervisor_review"]

    @pytest.mark.asyncio
    async def test_caller_supplied_human_review_ignored_on_the_permissive_pole(
        self, tmp_path: Path
    ) -> None:
        # The override is inert in both directions — the durable `false`
        # decides, and the attempted `true` is reported as ignored.
        _write_session_yaml(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\nhuman_review: false\n",
        )
        result = await resolve_gate_for_toplevel(
            gate="merge", context={"human_review": True}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert payload["effect"] == "auto-advance"
        assert "human_review" in payload["ignored_context_fields"]

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
            "friction_level: adaptive\nhuman_review: false\n"
            "gate_overrides:\n  merge: auto-advance\n",
        )
        _write_project_policy(tmp_path, "overrides:\n  merge: ask\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_missing_session_yaml_parks_at_the_review_boundary(self, tmp_path: Path) -> None:
        # ADR-0022 D-1: an unconfigured repo resolves at the single baseline
        # rather than a retired `strict` posture — and the safe fallback
        # direction now comes from `supervisor_review` defaulting to
        # `required`, which parks a team-shaped repo at request_review.
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert payload["effect"] == "ask"
        assert "supervisor_review" in payload["floors_applied"]
        assert "preset:adaptive" in payload["reason"]

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
    async def test_unknown_context_field_ignored_and_surfaced(self, tmp_path: Path) -> None:
        # GH-854 F1: an unknown context key is dropped and reported on the wire
        # under ``ignored_context_fields`` rather than hard-failing the call.
        result = await resolve_gate_for_toplevel(
            gate="merge", context={"vibe": "good"}, toplevel=str(tmp_path)
        )
        payload = result.to_dict()
        assert "error" not in payload
        assert payload["ignored_context_fields"] == ["vibe"]

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
            "active_modes: [solo-maintainer]\nallowed_overlays: []\n",
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
            ""
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
            "active_modes: [solo-maintainer]\n",
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
            "walk_away: true\nallowed_overlays: []\n",
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
            "gate_preset: adaptive\ngate_overlays: [solo-maintainer]\nallowed_overlays: []\n",
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
            "supervisor_review": "required",
        }

    def test_missing_file_yields_soft_defaults(self, tmp_path: Path) -> None:
        inputs = SessionYamlDocument(toplevel=str(tmp_path)).read_gate_policy_inputs()
        assert inputs == {
            # ``None``, not ``"strict"``: the gate layer must be able to tell
            # "no legacy posture declared" from "explicitly strict" (GH-1159).
            "friction_level": None,
            "active_modes": [],
            "walk_away": False,
            "gate_overrides": {},
            "gate_preset": None,
            "gate_overlays": [],
            "allowed_overlays": None,
            "supervisor_review": "required",
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
        _write_session_yaml(tmp_path, "gate_preset: adaptive\nsupervisor_review: none\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "auto-advance"
        assert "preset:adaptive" in payload["reason"]

    @pytest.mark.asyncio
    async def test_retired_gate_preset_errors_rather_than_escalating(self, tmp_path: Path) -> None:
        # GH-1159: a config still naming a retired preset must fail loudly,
        # not silently resolve at the more autonomous single baseline.
        _write_session_yaml(tmp_path, "gate_preset: strict\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert "Unknown preset 'strict'" in result.to_dict()["error"]

    @pytest.mark.asyncio
    async def test_gate_overlays_apply_over_new_preset(self, tmp_path: Path) -> None:
        _write_session_yaml(tmp_path, "gate_preset: adaptive\ngate_overlays: [solo-maintainer]\n")
        result = await resolve_gate_for_toplevel(
            gate="request_review", context={}, toplevel=str(tmp_path)
        )
        # The baseline auto-advances request_review; the overlay skips it —
        # and the solo shape moves the supervisor park to `merge`, so the
        # floor does not land here.
        assert result.to_dict()["effect"] == "skip"

    @pytest.mark.asyncio
    async def test_new_style_preset_outranks_legacy_keys(self, tmp_path: Path) -> None:
        # Both shapes present — the new-style gate_preset wins (D-4).
        _write_session_yaml(
            tmp_path,
            "friction_level: strict\ngate_preset: adaptive\nsupervisor_review: none\n",
        )
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
            "gate_preset: adaptive\nactive_modes: [solo-maintainer]\n",
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
        _write_session_yaml(tmp_path, "gate_preset: adaptive\nhuman_review: false\n")
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
        _write_session_yaml(tmp_path, "gate_preset: adaptive\nhuman_review: false\n")
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        assert result.to_dict()["effect"] == "auto-advance"

    @pytest.mark.asyncio
    async def test_sink_write_failure_is_swallowed(self, tmp_path: Path) -> None:
        # The doubt_sink write is best-effort — an OSError must not break
        # the resolution (the record still returns in the payload).
        _write_session_yaml(tmp_path, "gate_preset: adaptive\nhuman_review: false\n")
        sink = tmp_path / DOUBT_SINK_RELPATH
        sink.parent.mkdir(parents=True, exist_ok=True)
        sink.mkdir()  # a directory where the record file goes → append raises
        result = await resolve_gate_for_toplevel(gate="merge", context={}, toplevel=str(tmp_path))
        payload = result.to_dict()
        assert payload["effect"] == "auto-advance"
        assert payload["record"].startswith("⚙ gate:merge auto-advance")


class TestPresetPinTools:
    """The GH-855 durable-pin MCP surface behind the Phase-0 gate."""

    @pytest.fixture
    def zebra_repo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        main = tmp_path / "work" / "bl-zebra"
        (main / ".git").mkdir(parents=True)
        monkeypatch.setattr(
            "dev10x.session.preset_pin._common_dir", lambda *, cwd: str(main / ".git")
        )
        return main

    @pytest.mark.asyncio
    async def test_pin_and_status_round_trip_across_worktrees(self, zebra_repo: Path) -> None:
        """GH-855 AC: pin in `<repo>-3`, and `<repo>-9` sees it — no re-ask."""
        from dev10x.mcp.gate_tools import pin_gate_preset, preset_pin_status

        before = await preset_pin_status(cwd="/work/bl/.worktrees/bl-zebra-3")
        assert before["pinned"] is False

        pinned = await pin_gate_preset(preset="adaptive", cwd="/work/bl/.worktrees/bl-zebra-3")
        assert pinned["match"] == ["*/bl-zebra", "*/bl-zebra-*"]

        after = await preset_pin_status(cwd="/work/bl/.worktrees/bl-zebra-9")
        assert after["pinned"] is True
        assert after["prefs"]["gate_preset"] == "adaptive"

    @pytest.mark.asyncio
    async def test_pin_reports_an_unknown_scope_as_a_wire_error(self, zebra_repo: Path) -> None:
        from dev10x.mcp.gate_tools import pin_gate_preset

        payload = await pin_gate_preset(preset="adaptive", scope="galaxy")

        assert "unknown pin scope" in payload["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"preset": "adaptiv"}, "unknown preset"),
            ({"preset": "adaptive", "overlays": ["sollo"]}, "unknown overlay"),
            ({"preset": "adaptive", "gate_overrides": {"marge": "ask"}}, "unknown gate"),
        ],
    )
    async def test_pin_rejects_invalid_values_at_the_wire(
        self, zebra_repo: Path, kwargs: dict, expected: str
    ) -> None:
        """An agent's hallucinated value must not reach the durable file.

        Writing it would make every later resolve_gate for this repo fail
        with UnknownPresetError until someone re-pinned by hand.
        """
        from dev10x.mcp.gate_tools import pin_gate_preset

        assert expected in (await pin_gate_preset(**kwargs))["error"]

    @pytest.mark.asyncio
    async def test_pin_forwards_overlays_and_overrides(self, zebra_repo: Path) -> None:
        from dev10x.mcp.gate_tools import pin_gate_preset

        payload = await pin_gate_preset(
            preset="adaptive", overlays=["afk"], gate_overrides={"merge": "ask"}
        )

        assert payload["prefs"]["gate_overlays"] == ["afk"]
        assert payload["prefs"]["gate_overrides"] == {"merge": "ask"}

    @pytest.mark.asyncio
    async def test_status_reports_a_wire_error_outside_a_repo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.mcp.gate_tools import preset_pin_status

        monkeypatch.setattr("dev10x.session.preset_pin._common_dir", lambda *, cwd: None)
        monkeypatch.setattr("dev10x.session.preset_pin._bounded_toplevel", lambda *, cwd: None)

        assert "Not in a git repository" in (await preset_pin_status())["error"]


class TestHumanReviewStatusTool:
    """ADR-0019 / GH-950: the sanctioned MCP read of the review posture.

    Without this tool the three skill call sites named `read_human_review()`
    — a plain Python method no LLM orchestrator can invoke — which made the
    documented step unimplementable (PR #999 review finding).
    """

    @pytest.mark.asyncio
    async def test_renamed_tool_reports_the_enum_and_the_alias(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # GH-1161: `supervisor_review_status` is the current name; the
        # boolean `human_review` key rides along for one release so callers
        # that still branch on it keep working.
        from dev10x.mcp.gate_tools import supervisor_review_status

        _write_session_yaml(tmp_path, "supervisor_review: none\n")
        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: str(tmp_path)),
        )

        payload = await supervisor_review_status()

        assert payload["supervisor_review"] == "none"
        assert payload["human_review"] is False
        assert payload["repo_root"] == str(tmp_path)

    @pytest.mark.asyncio
    async def test_renamed_tool_defaults_to_required(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.mcp.gate_tools import supervisor_review_status

        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: str(tmp_path)),
        )
        assert (await supervisor_review_status())["supervisor_review"] == "required"

    @pytest.mark.asyncio
    async def test_deprecated_tool_name_still_answers(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.mcp.gate_tools import human_review_status

        _write_session_yaml(tmp_path, "supervisor_review: none\n")
        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: str(tmp_path)),
        )
        assert (await human_review_status())["supervisor_review"] == "none"

    @pytest.mark.asyncio
    async def test_reports_false_from_durable_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.mcp.gate_tools import human_review_status

        _write_session_yaml(tmp_path, "human_review: false\n")
        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: str(tmp_path)),
        )

        payload = await human_review_status()

        assert payload["human_review"] is False
        assert payload["repo_root"] == str(tmp_path)

    @pytest.mark.asyncio
    async def test_linked_worktree_reports_the_repo_posture(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """GH-1000: this tool and the merge gate must not disagree.

        A linked worktree whose directory name matches no `friction.yaml`
        glob resolves the repo root (GH-978). Reading from the raw toplevel
        would report `true` here while `resolve_gate(gate="merge")` read the
        repo's `false` and lifted its floor — one durable fact, two answers.
        """
        import yaml

        from dev10x.domain.dev10x_paths import Dev10xConfigDir
        from dev10x.mcp.gate_tools import human_review_status
        from dev10x.session import preset_pin

        repo = tmp_path / "work" / "bl-zebra"
        (repo / ".git").mkdir(parents=True)
        worktree = repo / ".claude" / "worktrees" / "agent-a194a6736f7f86b6c"
        worktree.mkdir(parents=True)
        monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(repo / ".git"))

        friction = Dev10xConfigDir.friction_yaml()
        friction.parent.mkdir(parents=True, exist_ok=True)
        friction.write_text(
            yaml.safe_dump(
                {
                    "defaults": {},
                    "projects": [{"match": ["*/bl-zebra", "*/bl-zebra-*"], "human_review": False}],
                }
            )
        )
        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: str(worktree)),
        )

        assert (await human_review_status())["human_review"] is False

    @pytest.mark.asyncio
    async def test_defaults_to_true_when_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Absent means humans review — the safe direction."""
        from dev10x.mcp.gate_tools import human_review_status

        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: str(tmp_path)),
        )

        assert (await human_review_status())["human_review"] is True

    @pytest.mark.asyncio
    async def test_malformed_value_fails_toward_more_oversight(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dev10x.mcp.gate_tools import human_review_status

        _write_session_yaml(tmp_path, 'human_review: "no"\n')
        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: str(tmp_path)),
        )

        assert (await human_review_status())["human_review"] is True

    @pytest.mark.asyncio
    async def test_reports_a_wire_error_outside_a_repo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.mcp.gate_tools import human_review_status

        monkeypatch.setattr(
            "dev10x.domain.git_context.GitContext.toplevel",
            property(lambda self: None),
        )

        assert "Not in a git repository" in (await human_review_status())["error"]
