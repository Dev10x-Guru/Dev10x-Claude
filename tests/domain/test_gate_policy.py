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
    SHIPPED_PRESETS,
    SUPERVISOR_REVIEW_NONE,
    SUPERVISOR_REVIEW_REQUIRED,
    GateContext,
    GateEffect,
    GateResolution,
    UnknownPresetError,
    UnknownToggleError,
    coerce_supervisor_review,
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
    # These exercise the merge gate's PRESET/OVERRIDE mechanics, so they
    # pass `human_review=False` to lift the ADR-0019 precondition floor
    # (GH-1000) that would otherwise short-circuit every one of them. The
    # floor's own behaviour is covered under "human_review as a merge
    # precondition" below.

    def test_merge_is_auto_advance_at_adaptive_by_default(self) -> None:
        resolution = resolve_gate(
            gate="merge", context=GateContext(human_review=False), preset="adaptive"
        )
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
            context=GateContext(human_review=False),
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

    # --- human_review as a merge precondition (ADR-0019 #3, GH-1000) ---

    def test_human_review_floors_the_merge_gate(self) -> None:
        # The default pole: humans review here, so the agent does not merge
        # on its own however permissive the preset and overlays are.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=True),
            preset="adaptive",
            overlays=["solo-maintainer", "afk"],
            session_overrides={"merge": AUTO_ADVANCE},
        )
        assert resolution.effect is GateEffect.ASK
        assert "human_review" in resolution.floors_applied

    def test_human_review_floor_names_its_remedy(self) -> None:
        # GH-1056: the floor is correct, but an unattended run that trips it
        # froze on an `ask` whose reason named only the floor — leaving the
        # operator to guess that a durable key, not the preset, held it.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=True),
            preset="adaptive",
            overlays=["solo-maintainer", "afk"],
        )
        assert "human_review: false" in resolution.reason
        assert "friction.yaml" in resolution.reason

    def test_action_floors_carry_no_remedy(self) -> None:
        # An action floor has no config escape by design, so its reason must
        # not imply one.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False, secret_access=True),
            preset="adaptive",
        )
        assert resolution.effect is GateEffect.ASK
        assert "friction.yaml" not in resolution.reason

    def test_human_review_defaults_to_flooring_when_unset(self) -> None:
        # An omitted fact must resolve toward oversight: an unconfigured
        # repo keeps a human on the merge.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(),
            preset="adaptive",
            overlays=["solo-maintainer", "afk"],
        )
        assert resolution.effect is GateEffect.ASK
        assert "human_review" in resolution.floors_applied

    def test_no_human_review_lets_the_merge_gate_resolve(self) -> None:
        # With humans out of the loop the floor lifts — and only then does
        # the preset get to decide.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False, supervisor_review=SUPERVISOR_REVIEW_NONE),
            preset="adaptive",
            overlays=["solo-maintainer", "afk"],
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE
        assert "human_review" not in resolution.floors_applied

    def test_human_review_floor_is_scoped_to_merge(self) -> None:
        # The flag's other consequences live in skills, not gates: it must
        # not quietly floor every unrelated gate.
        resolution = resolve_gate(
            gate="thread_resolution",
            context=GateContext(human_review=True),
            preset="adaptive",
        )
        assert resolution.floors_applied == []

    def test_no_human_review_cannot_re_admit_a_withheld_merge(self) -> None:
        # The composition invariant: both must agree, either can veto.
        # A project pin of `merge: ask` still wins — clearing human_review
        # is a precondition, never a grant.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False),
            preset="adaptive",
            overlays=["solo-maintainer", "afk"],
            project_overrides={"merge": "ask"},
        )
        assert resolution.effect is GateEffect.ASK

    def test_no_human_review_cannot_re_admit_a_dropped_overlay(self) -> None:
        # allowed_overlays drops solo-maintainer upstream of resolution, so
        # the repo reads as team-shaped and the supervisor_review floor lands
        # on request_review — while a `merge: ask` project pin still governs
        # the merge itself. human_review is not an overlay and cannot put the
        # dropped one back to reach auto-advance.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False),
            preset=BASELINE_PRESET,
            overlays=[],
            project_overrides={"merge": "ask"},
        )
        assert resolution.effect is GateEffect.ASK
        assert resolution.effect is not GateEffect.AUTO_ADVANCE

    def test_a_safety_floor_still_outranks_cleared_human_review(self) -> None:
        # human_review: false lifts its own floor only. An unrelated safety
        # floor is untouched by it.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False, secret_access=True),
            preset="adaptive",
            overlays=["solo-maintainer", "afk"],
            session_overrides={"merge": AUTO_ADVANCE},
        )
        assert resolution.effect is GateEffect.ASK
        assert "secret_access" in resolution.floors_applied

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
        # human_review=False so the ADR-0019 floor does not short-circuit
        # ahead of toggle evaluation — the bad value must still be reached.
        with pytest.raises(UnknownToggleError):
            resolve_gate(
                gate="merge",
                context=GateContext(human_review=False),
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
            context=GateContext(human_review=False, supervisor_review=SUPERVISOR_REVIEW_NONE),
            preset=preset,
            overlays=overlays,
        )
        assert resolution.effect is GateEffect.AUTO_ADVANCE


class TestSupervisorReviewFloor:
    # ADR-0022 D-3/D-5. `human_review=False` throughout so the ADR-0019
    # floor does not short-circuit the merge rows before this floor is
    # reached — GH-1161 collapses the two into one key.

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
            context=GateContext(human_review=False, supervisor_review=supervisor_review),
            preset=BASELINE_PRESET,
            overlays=overlays,
        )
        assert resolution.effect is expected

    def test_required_does_not_floor_the_other_shape_s_gate(self) -> None:
        # In a solo repo the park sits at merge, so request_review is not
        # floored — it is skipped by the overlay, as before.
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(human_review=False, supervisor_review=SUPERVISOR_REVIEW_REQUIRED),
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
                human_review=False,
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
            context=GateContext(human_review=False),
            preset=BASELINE_PRESET,
        )
        assert resolution.effect is GateEffect.ASK
        assert "supervisor_review" in resolution.floors_applied

    def test_floor_names_its_remedy(self) -> None:
        resolution = resolve_gate(
            gate="request_review",
            context=GateContext(human_review=False),
            preset=BASELINE_PRESET,
        )
        assert "review:cleared" in resolution.reason
        assert "supervisor_review: none" in resolution.reason

    def test_none_cannot_re_admit_a_withheld_gate(self) -> None:
        # `none` is a PRECONDITION, never a grant: a project pin still wins.
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False, supervisor_review=SUPERVISOR_REVIEW_NONE),
            preset=BASELINE_PRESET,
            overlays=self.SOLO,
            project_overrides={"merge": "ask"},
        )
        assert resolution.effect is GateEffect.ASK

    def test_a_safety_floor_still_outranks_a_cleared_supervisor(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(
                human_review=False,
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
            ("  None  ", SUPERVISOR_REVIEW_NONE),
            ("required", SUPERVISOR_REVIEW_REQUIRED),
            # Everything malformed fails toward MORE oversight.
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

    # human_review=False throughout: with the ADR-0019 floor active these
    # would resolve to ASK whether or not the injection took effect, so the
    # assertion would pass vacuously.

    def test_injected_presets_replace_the_domain_default(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False),
            preset="custom",
            shipped_presets={"custom": {**SHIPPED_PRESETS["adaptive"], "merge": "ask"}},
        )
        assert resolution.effect is GateEffect.ASK

    def test_injected_overlays_replace_the_domain_default(self) -> None:
        resolution = resolve_gate(
            gate="merge",
            context=GateContext(human_review=False),
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
        # human_review defaults to True, so the ADR-0019 floor asks.
        assert (
            resolve_gate(
                gate="merge", context=GateContext(), preset=BASELINE_PRESET
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
