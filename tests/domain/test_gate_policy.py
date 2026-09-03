"""Tests for the ADR-0016 gate-policy resolver spike.

The parametrized cases replay the four audit scenarios that motivated
the design (GH-742, GH-743, GH-744, GH-745) plus the layer-precedence
and floor invariants, and the D-9 guided-preset posture (GH-748).
"""

from __future__ import annotations

import pytest

from dev10x.domain.gate_policy import (
    AUTO_ADVANCE,
    BASELINE_PRESET,
    KNOWN_TOGGLES,
    MIGRATOR_COMMAND,
    SHIPPED_PRESETS,
    SUPERVISOR_REVIEW_NONE,
    SUPERVISOR_REVIEW_REQUIRED,
    GateContext,
    GateEffect,
    GateResolution,
    UnknownPresetError,
    UnknownToggleError,
    coerce_supervisor_review,
    legacy_config_message,
    legacy_policy_keys,
    legacy_session_mapping,
    resolve_gate,
    supervisor_review_gate,
)


class TestGatePolicyResolver:
    # --- Audit scenario 1: GH-742 F1 — stale session.yaml auto-merge ---

    @pytest.mark.parametrize("preset", ["adaptive"])
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

    @pytest.mark.parametrize("preset", ["adaptive"])
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
    #
    # These exercise the merge gate's PRESET/OVERRIDE mechanics with no
    # overlays, so the repo reads as team-shaped and the ADR-0022 review
    # boundary parks at `request_review` rather than short-circuiting them.
    # That floor's own behaviour is covered in TestSupervisorReviewFloor.

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

    def test_solo_maintainer_overlay_skips_review_request(self) -> None:
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(),
            preset="adaptive",
            overlays=["solo-maintainer"],
        )
        assert resolution.effect is GateEffect.SKIP

    # --- ADR-0022 D-1: adaptive is the sole shipped base preset ---

    def test_adaptive_is_the_only_shipped_preset(self) -> None:
        assert set(SHIPPED_PRESETS) == {BASELINE_PRESET}

    @pytest.mark.parametrize("preset", ["strict", "guided"])
    def test_retired_presets_fail_loudly(self, preset: str) -> None:
        # A retired name must NOT resolve at the more autonomous baseline —
        # a repo that asked for `strict` silently gaining walk-away merge
        # autonomy is the one outcome the collapse must never produce.
        with pytest.raises(UnknownPresetError):
            resolve_gate(gate="merge", context=GateContext(), preset=preset)

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
    def test_baseline_auto_advances_mechanical_gates(self, gate: str) -> None:
        resolution = resolve_gate(gate=gate, context=GateContext(), preset=BASELINE_PRESET)
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    # --- Audit scenario 4: GH-745 F1 — zero-VALID batch auto-flow ---

    @pytest.mark.parametrize("preset", ["adaptive"])
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

    @pytest.mark.parametrize("preset", ["adaptive"])
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

    # --- Floor remedies ---
    #
    # The review-boundary floor itself (ADR-0019 #3 / GH-1000, renamed and
    # generalised by ADR-0022 D-2) is covered in TestSupervisorReviewFloor.

    def test_action_floors_carry_no_remedy(self) -> None:
        # An action floor has no config escape by design, so its reason must
        # not imply one.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(secret_access=True),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.ASK
        assert "friction.yaml" not in resolution.reason

    def test_review_floor_does_not_leak_onto_unrelated_gates(self) -> None:
        # The durable fact's other consequences live in skills, not gates: it
        # must not quietly floor every unrelated gate.
        resolution = resolve_gate(
            gate="thread_resolution",
            context=GateContext(supervisor_review=SUPERVISOR_REVIEW_REQUIRED),
            preset="adaptive",
        )
        assert resolution.floors_applied == []

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
        # No overlays, so no review floor short-circuits ahead of toggle
        # evaluation on this gate — the bad value must still be reached.
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


class TestLegacyPolicyKeys:
    """GH-1162: naming the v1 keys is what makes the refusal actionable."""

    V2 = {
        "friction_level": None,
        "walk_away": False,
        "active_modes": [],
        "gate_preset": None,
        "gate_overlays": [],
    }

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({}, []),
            # Structural modes were never gate concerns — not v1 markers.
            ({"active_modes": ["review-deferred", "swarm-child"]}, []),
            # A v2 config naming its overlays explicitly is clean.
            ({"gate_overlays": ["solo-maintainer", "afk"]}, []),
            ({"friction_level": "strict"}, ["friction_level"]),
            # Any value counts: the three-way choice is gone, so declaring
            # a posture at all is v1 vocabulary.
            ({"friction_level": "adaptive"}, ["friction_level"]),
            ({"walk_away": True}, ["walk_away"]),
            ({"active_modes": ["solo-maintainer"]}, ["active_modes: solo-maintainer"]),
            # The migrator materialises the overlay and leaves the mode in
            # place, so a migrated config states it twice and is clean.
            (
                {"active_modes": ["solo-maintainer"], "gate_overlays": ["solo-maintainer"]},
                [],
            ),
            ({"gate_preset": "guided"}, ["gate_preset: guided"]),
            ({"gate_preset": "adaptive"}, []),
            (
                {"friction_level": "strict", "walk_away": True},
                ["friction_level", "walk_away"],
            ),
        ],
    )
    def test_detects_only_the_seam_s_own_inputs(
        self, overrides: dict[str, object], expected: list[str]
    ) -> None:
        assert legacy_policy_keys(**{**self.V2, **overrides}) == expected  # type: ignore[arg-type]

    def test_message_names_the_migrator_command(self) -> None:
        message = legacy_config_message(keys=["friction_level"])
        assert MIGRATOR_COMMAND in message
        assert "friction_level" in message

    def test_retired_preset_name_points_at_the_migrator(self) -> None:
        with pytest.raises(UnknownPresetError, match=MIGRATOR_COMMAND):
            resolve_gate(gate="merge", context=GateContext(), preset="strict")

    def test_plain_typo_gets_no_migrator_hint(self) -> None:
        with pytest.raises(UnknownPresetError) as excinfo:
            resolve_gate(gate="merge", context=GateContext(), preset="adpative")
        assert MIGRATOR_COMMAND not in str(excinfo.value)


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
            # The seam is a pure read-compat mapping and stays 1:1 even for a
            # retired preset name — resolve_gate is where that now fails loud
            # (GH-1162 retires the seam once the migrator ships).
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
            gate="merge",
            context=GateContext(supervisor_review=SUPERVISOR_REVIEW_NONE),
            preset=preset,
            overlays=overlays,
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE


class TestSupervisorReviewFloor:
    # ADR-0022 D-3/D-5. This floor IS the ADR-0019 `human_review` floor,
    # renamed and generalised (GH-1161) — the two are one key, not two.

    SOLO = ["solo-maintainer"]
    TEAM: list[str] = []

    @pytest.mark.parametrize(
        ("overlays", "supervisor_review", "gate", "expected"),
        [
            # The four cells of the ADR-0022 D-3 table.
            (SOLO, SUPERVISOR_REVIEW_NONE, "merge", GateEffect.AUTO_ADVANCE),
            (SOLO, SUPERVISOR_REVIEW_REQUIRED, "merge", GateEffect.ASK),
            (TEAM, SUPERVISOR_REVIEW_NONE, "request_review", GateEffect.AUTO_ADVANCE),
            (TEAM, SUPERVISOR_REVIEW_REQUIRED, "request_review", GateEffect.ASK),
        ],
    )
    def test_effect_point_moves_with_repo_shape(
        self,
        overlays: list[str],
        supervisor_review: str,
        gate: str,
        expected: GateEffect,
    ) -> None:
        resolution = resolve_gate(
            gate=gate,
            context=GateContext(supervisor_review=supervisor_review),
            preset=BASELINE_PRESET,
            overlays=overlays,
        )
        assert resolution.effect is expected

    def test_required_does_not_floor_the_other_shape_s_gate(self) -> None:
        # In a solo repo the park sits at merge, so request_review is not
        # floored — it is skipped by the overlay, as before.
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(supervisor_review=SUPERVISOR_REVIEW_REQUIRED),
            preset=BASELINE_PRESET,
            overlays=self.SOLO,
        )
        assert "supervisor_review" not in resolution.floors_applied

    def test_required_precedes_rather_than_replaces_the_team_request(self) -> None:
        # Team row: `required` inserts a park BEFORE the team request; it
        # never removes the request step itself, which stays auto-advance
        # once the supervisor has cleared.
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(
                supervisor_review=SUPERVISOR_REVIEW_REQUIRED,
                supervisor_cleared=True,
            ),
            preset=BASELINE_PRESET,
            overlays=self.TEAM,
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE

    def test_floor_defaults_to_required_when_unset(self) -> None:
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(),
            preset=BASELINE_PRESET,
        )
        assert resolution.effect is GateEffect.ASK
        assert "supervisor_review" in resolution.floors_applied

    def test_floor_names_its_remedy(self) -> None:
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(),
            preset=BASELINE_PRESET,
        )
        assert "review:cleared" in resolution.reason
        assert "supervisor_review: none" in resolution.reason

    def test_none_cannot_re_admit_a_withheld_gate(self) -> None:
        # `none` is a PRECONDITION, never a grant: a project pin still wins.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(supervisor_review=SUPERVISOR_REVIEW_NONE),
            preset=BASELINE_PRESET,
            overlays=self.SOLO,
            project_overrides={"merge": "ask"},
        )
        assert resolution.effect is GateEffect.ASK

    def test_a_safety_floor_still_outranks_a_cleared_supervisor(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(
                supervisor_review=SUPERVISOR_REVIEW_NONE,
                secret_access=True,
            ),
            preset=BASELINE_PRESET,
            overlays=self.SOLO,
        )
        assert resolution.effect is GateEffect.ASK
        assert "secret_access" in resolution.floors_applied

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("none", SUPERVISOR_REVIEW_NONE),
            ("  none  ", SUPERVISOR_REVIEW_NONE),  # YAML whitespace artefact
            ("required", SUPERVISOR_REVIEW_REQUIRED),
            # Everything malformed fails toward MORE oversight — including
            # `None`, likelier a stray Python literal than a considered answer.
            ("None", SUPERVISOR_REVIEW_REQUIRED),
            ("no", SUPERVISOR_REVIEW_REQUIRED),
            (False, SUPERVISOR_REVIEW_REQUIRED),
            (None, SUPERVISOR_REVIEW_REQUIRED),
            ([], SUPERVISOR_REVIEW_REQUIRED),
        ],
    )
    def test_coercion_only_honours_the_exact_none_literal(
        self, raw: object, expected: str
    ) -> None:
        assert coerce_supervisor_review(raw) == expected

    @pytest.mark.parametrize(
        ("solo_repo", "expected"),
        [(True, "merge"), (False, "request_review")],
    )
    def test_effect_point_is_named_by_repo_shape(self, solo_repo: bool, expected: str) -> None:
        assert supervisor_review_gate(solo_repo=solo_repo) == expected


class TestInjectedShippedPresets:
    # ADR-0016 #752: the infra tier injects YAML-hydrated preset maps.

    # No overlays throughout, so the review boundary parks at request_review
    # and cannot resolve these merge assertions to ASK regardless of whether
    # the injection took effect — which would make them pass vacuously.

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
                shipped_presets={"only-one": SHIPPED_PRESETS[BASELINE_PRESET]},
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
        # supervisor_review defaults to `required`, so the review floor asks
        # at the gate a team-shaped repo parks at.
        assert (
            resolve_gate(
                gate="request_review", context=GateContext(), preset=BASELINE_PRESET
            ).visible_record()
            is None
        )

    def test_skip_has_no_record(self) -> None:
        assert (
            resolve_gate(
                gate="request_review",
                context=GateContext(),
                preset=BASELINE_PRESET,
                overlays=["solo-maintainer"],
            ).visible_record()
            is None
        )
