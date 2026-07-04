"""Tests for the ADR-0016 gate-policy resolver spike.

The parametrized cases replay the four audit scenarios that motivated
the design (GH-742, GH-743, GH-744, GH-745) plus the layer-precedence
and floor invariants, and the D-9 guided-preset posture (GH-748).
"""

from __future__ import annotations

import pytest

from dev10x.domain.gate_policy import (
    AUTO_ADVANCE,
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

    @pytest.mark.parametrize("preset", ["guided", "adaptive"])
    def test_stale_session_adoption_asks(self, preset: str) -> None:
        resolution = resolve_gate(
            gate="session_adoption",
            context=GateContext(session_stale=True),
            preset=preset,
        )
        assert resolution.effect is GateEffect.ASK
        assert "stale=true" in resolution.reason

    def test_fresh_session_adoption_auto_advances_at_adaptive(self) -> None:
        resolution = resolve_gate(
            gate="session_adoption",
            context=GateContext(session_stale=False),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    def test_afk_overlay_trusts_session_adoption_even_when_stale(self) -> None:
        resolution = resolve_gate(
            gate="session_adoption",
            context=GateContext(session_stale=True),
            preset="adaptive",
            overlays=["afk"],
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    # --- Audit scenario 2: GH-745 F4 — bot vs human thread keying ---

    @pytest.mark.parametrize("preset", ["guided", "adaptive"])
    @pytest.mark.parametrize(
        "gate",
        ["triage_response", "thread_resolution", "comment_hide"],
    )
    @pytest.mark.parametrize(
        ("author_type", "expected_effect"),
        [
            ("bot", GateEffect.AUTO_ADVANCE),
            ("human", GateEffect.ASK),
            (None, GateEffect.ASK),  # unknown author resolves as human
        ],
    )
    def test_batch_gates_key_on_author_type(
        self, preset: str, gate: str, author_type: str | None, expected_effect: GateEffect
    ) -> None:
        # GH-745 F4: all three batch gates — triage_response,
        # thread_resolution, and comment_hide — auto-advance for bot
        # authors and always gate for human (or unknown) authors.
        resolution = resolve_gate(
            gate=gate,
            context=GateContext(author_type=author_type, valid_fixup_count=1),
            preset=preset,
        )
        assert resolution.effect is expected_effect

    # --- Audit scenario 3: GH-743/744 — the merge human boundary ---

    def test_merge_is_auto_advance_at_adaptive_by_default(self) -> None:
        resolution = resolve_gate(gate="merge", context=GateContext(), preset="adaptive")
        assert resolution.effect is GateEffect.AUTO_ADVANCE

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
            session_overrides={"merge": AUTO_ADVANCE},
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    def test_merge_asks_at_strict(self) -> None:
        resolution = resolve_gate(gate="merge", context=GateContext(), preset="strict")
        assert resolution.effect is GateEffect.ASK

    def test_merge_is_skipped_at_guided(self) -> None:
        # D-9 (GH-748): merge is a strictly human action through the PR
        # UI at guided — the agent's merge step does not exist. The
        # session hands off after request-review or monitors approval.
        resolution = resolve_gate(gate="merge", context=GateContext(), preset="guided")
        assert resolution.effect is GateEffect.SKIP
        assert resolution.resolved_option is None

    def test_solo_maintainer_overlay_skips_review_request(self) -> None:
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(),
            preset="guided",
            overlays=["solo-maintainer"],
        )
        assert resolution.effect is GateEffect.SKIP

    # --- D-9 (GH-748): light-AFK guided posture ---

    @pytest.mark.parametrize(
        "gate",
        [
            "plan_approval",
            "batch_layout",
            "strategy_choice",
            "artifact_preview",
            "yagni_routing",
            "shipping_continuation",
            "workspace_choice",
        ],
    )
    def test_guided_auto_advances_mechanical_gates(self, gate: str) -> None:
        resolution = resolve_gate(gate=gate, context=GateContext(), preset="guided")
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    @pytest.mark.parametrize("gate", ["request_review", "external_notify", "completion_signoff"])
    def test_guided_supervises_team_interactions(self, gate: str) -> None:
        resolution = resolve_gate(gate=gate, context=GateContext(), preset="guided")
        assert resolution.effect is GateEffect.ASK

    def test_guided_differs_from_adaptive_only_at_the_human_boundary(self) -> None:
        guided = SHIPPED_PRESETS["guided"]
        adaptive = SHIPPED_PRESETS["adaptive"]
        differing = {key for key in guided if guided[key] != adaptive[key]}
        assert differing == {"request_review", "merge", "completion_signoff"}

    def test_strict_fires_every_enum_gate(self) -> None:
        strict = SHIPPED_PRESETS["strict"]
        enum_values = {
            key: value
            for key, value in strict.items()
            if isinstance(value, str) and key not in {"doubt_sink"}
        }
        assert all(value == "ask" for value in enum_values.values())

    # --- Audit scenario 4: GH-745 F1 — zero-VALID batch auto-flow ---

    @pytest.mark.parametrize("preset", ["guided", "adaptive"])
    @pytest.mark.parametrize("gate", ["triage_response", "thread_resolution", "comment_hide"])
    def test_zero_valid_bot_batch_auto_flows(self, preset: str, gate: str) -> None:
        # GH-745 F1: the audit scenario was a batch of automated-reviewer
        # (bot) comments yielding zero VALID fixups; all three batch gates
        # must auto-advance rather than block.
        resolution = resolve_gate(
            gate=gate,
            context=GateContext(author_type="bot", valid_fixup_count=0),
            preset=preset,
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    @pytest.mark.parametrize("preset", ["guided", "adaptive"])
    @pytest.mark.parametrize("gate", ["triage_response", "thread_resolution", "comment_hide"])
    def test_zero_valid_human_batch_still_gates(self, preset: str, gate: str) -> None:
        # GH-745 F4 outranks F1 for human authors: hiding or dismissing a
        # teammate's comment needs sign-off even when there is no VALID
        # fixup to apply.
        resolution = resolve_gate(
            gate=gate,
            context=GateContext(author_type="human", valid_fixup_count=0),
            preset=preset,
        )
        assert resolution.effect is GateEffect.ASK

    def test_zero_valid_batch_asks_when_autoflow_disabled(self) -> None:
        # Project/session override path: a batch gate pinned to plain
        # AUTO_ADVANCE still honors zero_valid_autoflow.
        resolution = resolve_gate(
            gate="comment_hide",
            context=GateContext(valid_fixup_count=0),
            preset="adaptive",
            session_overrides={"comment_hide": AUTO_ADVANCE, "zero_valid_autoflow": False},
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
            session_overrides={"merge": AUTO_ADVANCE},
        )
        assert resolution.effect is GateEffect.ASK
        assert expected_floor in resolution.floors_applied

    def test_destructive_but_recoverable_is_not_floored(self) -> None:
        resolution = resolve_gate(
            gate="branch_cleanup",
            context=GateContext(destructive=True, branch_merged=True),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    def test_unmerged_branch_cleanup_asks_at_adaptive(self) -> None:
        resolution = resolve_gate(
            gate="branch_cleanup",
            context=GateContext(destructive=True, branch_merged=False),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.ASK

    @pytest.mark.parametrize(
        ("provably_safe", "expected_effect"),
        [(True, GateEffect.AUTO_ADVANCE), (False, GateEffect.ASK)],
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
        [(2, GateEffect.ASK), (3, GateEffect.AUTO_ADVANCE), (5, GateEffect.AUTO_ADVANCE)],
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

    # --- D-7: auto-advance resolutions are visible-record shaped ---

    def test_auto_advance_resolution_carries_option_reason_and_sink(self) -> None:
        resolution = resolve_gate(gate="plan_approval", context=GateContext(), preset="adaptive")
        assert resolution.effect is GateEffect.AUTO_ADVANCE
        assert resolution.resolved_option == "Recommended"
        assert resolution.log_to == "pr-description"
        assert "preset:adaptive" in resolution.reason

    def test_payload_is_wire_shaped(self) -> None:
        payload = resolve_gate(
            gate="plan_approval", context=GateContext(), preset="adaptive"
        ).to_payload()
        assert payload["effect"] == "auto-advance"
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
        assert resolution.effect is GateEffect.AUTO_ADVANCE


class TestInjectedShippedPresets:
    # ADR-0016 #752: the infra tier injects YAML-hydrated preset maps.

    def test_injected_presets_replace_the_domain_default(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(),
            preset="custom",
            shipped_presets={"custom": {**SHIPPED_PRESETS["adaptive"], "merge": "ask"}},
        )
        assert resolution.effect is GateEffect.ASK

    def test_injected_overlays_replace_the_domain_default(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(),
            preset="adaptive",
            overlays=["freeze"],
            shipped_overlays={"freeze": {"merge": "ask"}},
        )
        assert resolution.effect is GateEffect.ASK

    def test_unknown_preset_reports_injected_set(self) -> None:
        with pytest.raises(UnknownPresetError, match="only-one"):
            resolve_gate(
                gate="merge",
                context=GateContext(),
                preset="missing",
                shipped_presets={"only-one": SHIPPED_PRESETS["strict"]},
            )


class TestVisibleRecord:
    # ADR-0016 #754 / D-7: auto-advances carry a one-line transcript record.

    def test_auto_advance_formats_record(self) -> None:
        record = resolve_gate(
            gate="plan_approval", context=GateContext(), preset="adaptive"
        ).visible_record()
        assert record is not None
        assert record.startswith('⚙ gate:plan_approval auto-advance → "Recommended" (')
        assert record.endswith(")")

    def test_ask_has_no_record(self) -> None:
        assert (
            resolve_gate(gate="merge", context=GateContext(), preset="strict").visible_record()
            is None
        )

    def test_skip_has_no_record(self) -> None:
        assert (
            resolve_gate(gate="merge", context=GateContext(), preset="guided").visible_record()
            is None
        )
