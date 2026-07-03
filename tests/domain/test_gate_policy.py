"""Tests for the ADR-0016 gate-policy resolver spike.

The parametrized cases replay the four audit scenarios that motivated
the design (GH-742, GH-743, GH-744, GH-745) plus the layer-precedence
and floor invariants.
"""

from __future__ import annotations

import pytest

from dev10x.domain.gate_policy import (
    KNOWN_TOGGLES,
    SHIPPED_PRESETS,
    GateContext,
    GateEffect,
    GateResolution,
    UnknownPresetError,
    UnknownToggleError,
    legacy_session_mapping,
    resolve_gate,
)


class TestGatePolicyResolver:
    # --- Audit scenario 1: GH-742 F1 — stale session.yaml auto-merge ---

    def test_stale_session_adoption_asks_at_adaptive(self) -> None:
        resolution = resolve_gate(
            gate="session_adoption",
            context=GateContext(session_stale=True),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.ASK
        assert "stale=true" in resolution.reason

    def test_fresh_session_adoption_auto_resolves_at_adaptive(self) -> None:
        resolution = resolve_gate(
            gate="session_adoption",
            context=GateContext(session_stale=False),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.AUTO

    def test_afk_overlay_trusts_session_adoption_even_when_stale(self) -> None:
        resolution = resolve_gate(
            gate="session_adoption",
            context=GateContext(session_stale=True),
            preset="adaptive",
            overlays=["afk"],
        )
        assert resolution.effect is GateEffect.AUTO

    # --- Audit scenario 2: GH-745 F4 — bot vs human thread keying ---

    @pytest.mark.parametrize(
        ("author_type", "expected_effect"),
        [
            ("bot", GateEffect.AUTO),
            ("human", GateEffect.ASK),
            (None, GateEffect.ASK),  # unknown author resolves as human
        ],
    )
    def test_thread_resolution_keys_on_author_type_at_adaptive(
        self, author_type: str | None, expected_effect: GateEffect
    ) -> None:
        resolution = resolve_gate(
            gate="thread_resolution",
            context=GateContext(author_type=author_type, valid_fixup_count=1),
            preset="adaptive",
        )
        assert resolution.effect is expected_effect

    # --- Audit scenario 3: GH-743/744 — team repo pins merge at project tier ---

    def test_merge_is_auto_at_adaptive_by_default(self) -> None:
        resolution = resolve_gate(gate="merge", context=GateContext(), preset="adaptive")
        assert resolution.effect is GateEffect.AUTO

    def test_team_repo_project_pin_outranks_adaptive_preset(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(),
            preset="adaptive",
            project_overrides={"merge": "ask"},
        )
        assert resolution.effect is GateEffect.ASK

    def test_session_toggle_override_outranks_project_pin(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(),
            preset="adaptive",
            project_overrides={"merge": "ask"},
            session_overrides={"merge": "auto"},
        )
        assert resolution.effect is GateEffect.AUTO

    @pytest.mark.parametrize("preset", ["strict", "guided"])
    def test_merge_asks_at_attended_presets(self, preset: str) -> None:
        resolution = resolve_gate(gate="merge", context=GateContext(), preset=preset)
        assert resolution.effect is GateEffect.ASK

    def test_solo_maintainer_overlay_skips_review_request(self) -> None:
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(),
            preset="guided",
            overlays=["solo-maintainer"],
        )
        assert resolution.effect is GateEffect.SKIP

    # --- Audit scenario 4: GH-745 F1 — zero-VALID batch auto-flow ---

    def test_zero_valid_batch_auto_flows_at_adaptive(self) -> None:
        resolution = resolve_gate(
            gate="comment_hide",
            context=GateContext(valid_fixup_count=0),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.AUTO

    def test_zero_valid_batch_asks_when_autoflow_disabled(self) -> None:
        resolution = resolve_gate(
            gate="comment_hide",
            context=GateContext(valid_fixup_count=0),
            preset="adaptive",
            session_overrides={"comment_hide": "auto", "zero_valid_autoflow": False},
        )
        assert resolution.effect is GateEffect.ASK

    # --- Floors: deny-overrides ---

    @pytest.mark.parametrize(
        ("context", "expected_floor"),
        [
            (GateContext(secret_access=True), "secret_access"),
            (
                GateContext(destructive=True, irreversible=True),
                "destructive_irreversible",
            ),
            (GateContext(cross_author=True), "cross_author_push"),
            (GateContext(privacy_disclosure=True), "privacy_disclosure"),
            (GateContext(blocking=True), "blocking"),
        ],
    )
    def test_floors_force_ask_regardless_of_overrides(
        self, context: GateContext, expected_floor: str
    ) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=context,
            preset="adaptive",
            overlays=["solo-maintainer", "afk"],
            session_overrides={"merge": "auto"},
        )
        assert resolution.effect is GateEffect.ASK
        assert expected_floor in resolution.floors_applied

    def test_destructive_but_recoverable_is_not_floored(self) -> None:
        resolution = resolve_gate(
            gate="branch_cleanup",
            context=GateContext(destructive=True, branch_merged=True),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.AUTO

    def test_unmerged_branch_cleanup_asks_at_adaptive(self) -> None:
        resolution = resolve_gate(
            gate="branch_cleanup",
            context=GateContext(destructive=True, branch_merged=False),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.ASK

    @pytest.mark.parametrize(
        ("provably_safe", "expected_effect"),
        [(True, GateEffect.AUTO), (False, GateEffect.ASK)],
    )
    def test_history_rewrite_keys_on_provable_safety_at_adaptive(
        self, provably_safe: bool, expected_effect: GateEffect
    ) -> None:
        resolution = resolve_gate(
            gate="history_rewrite",
            context=GateContext(provably_safe=provably_safe),
            preset="adaptive",
        )
        assert resolution.effect is expected_effect

    def test_invalid_toggle_value_raises(self) -> None:
        with pytest.raises(UnknownToggleError):
            resolve_gate(
                gate="merge",
                context=GateContext(),
                preset="adaptive",
                session_overrides={"merge": "maybe"},
            )

    # --- Weight toggles ---

    @pytest.mark.parametrize(
        ("signals", "expected_effect"),
        [(2, GateEffect.ASK), (3, GateEffect.AUTO), (5, GateEffect.AUTO)],
    )
    def test_batch_layout_respects_ambiguity_floor(
        self, signals: int, expected_effect: GateEffect
    ) -> None:
        resolution = resolve_gate(
            gate="batch_layout",
            context=GateContext(overlap_signals=signals),
            preset="adaptive",
        )
        assert resolution.effect is expected_effect

    # --- D-7: auto resolutions are visible-record shaped ---

    def test_auto_resolution_carries_option_reason_and_sink(self) -> None:
        resolution = resolve_gate(gate="plan_approval", context=GateContext(), preset="adaptive")
        assert resolution.effect is GateEffect.AUTO
        assert resolution.resolved_option == "Recommended"
        assert resolution.log_to == "pr-description"
        assert "preset:adaptive" in resolution.reason

    def test_payload_is_wire_shaped(self) -> None:
        payload = resolve_gate(
            gate="plan_approval", context=GateContext(), preset="adaptive"
        ).to_payload()
        assert payload["effect"] == "auto"
        assert set(payload) == {
            "gate",
            "effect",
            "resolved_option",
            "log_to",
            "reason",
            "floors_applied",
            "anchor_recommendations",
        }

    # --- Preset integrity & errors ---

    def test_every_preset_covers_every_toggle(self) -> None:
        for name, preset in SHIPPED_PRESETS.items():
            assert set(preset) == set(KNOWN_TOGGLES), name

    def test_strict_differs_from_guided_only_by_anchoring_weights_staleness(
        self,
    ) -> None:
        strict = SHIPPED_PRESETS["strict"]
        guided = SHIPPED_PRESETS["guided"]
        differing = {key for key in strict if strict[key] != guided[key]}
        assert differing == {
            "anchor_recommendations",
            "autofix_confidence",
            "batch_ambiguity_floor",
            "session_adoption",
        }

    def test_unknown_gate_raises(self) -> None:
        with pytest.raises(UnknownToggleError):
            resolve_gate(gate="nonsense", context=GateContext(), preset="adaptive")

    def test_unknown_preset_raises(self) -> None:
        with pytest.raises(UnknownPresetError):
            resolve_gate(gate="merge", context=GateContext(), preset="turbo")

    def test_unknown_overlay_raises(self) -> None:
        with pytest.raises(UnknownPresetError):
            resolve_gate(
                gate="merge",
                context=GateContext(),
                preset="adaptive",
                overlays=["yolo"],
            )

    def test_user_preset_extends_shipped_set(self) -> None:
        team_preset = {**SHIPPED_PRESETS["adaptive"], "merge": "ask"}
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(),
            preset="team-afk",
            user_presets={"team-afk": team_preset},
        )
        assert resolution.effect is GateEffect.ASK


class TestLegacySessionMapping:
    @pytest.mark.parametrize(
        ("friction_level", "active_modes", "walk_away", "expected"),
        [
            ("adaptive", ["solo-maintainer"], False, ("adaptive", ["solo-maintainer"])),
            ("adaptive", [], True, ("adaptive", ["afk"])),
            (
                "adaptive",
                ["solo-maintainer", "review-deferred"],
                True,
                ("adaptive", ["solo-maintainer", "afk"]),
            ),
            ("guided", [], False, ("guided", [])),
        ],
    )
    def test_legacy_shapes_map_to_preset_and_overlays(
        self,
        friction_level: str,
        active_modes: list[str],
        walk_away: bool,
        expected: tuple[str, list[str]],
    ) -> None:
        assert (
            legacy_session_mapping(
                friction_level=friction_level,
                active_modes=active_modes,
                walk_away=walk_away,
            )
            == expected
        )

    def test_legacy_mapping_resolves_end_to_end(self) -> None:
        preset, overlays = legacy_session_mapping(
            friction_level="adaptive",
            active_modes=["solo-maintainer"],
            walk_away=False,
        )
        resolution: GateResolution = resolve_gate(
            gate="merge", context=GateContext(), preset=preset, overlays=overlays
        )
        assert resolution.effect is GateEffect.AUTO
