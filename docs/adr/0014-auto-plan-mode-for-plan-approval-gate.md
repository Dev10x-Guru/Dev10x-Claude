# 14. Add `auto-plan` mode to auto-approve only the plan gate

Date: 2026-06-25

## Status

Accepted — superseded by ADR-0016 Phase 2 (GH-755). The plan-gate
decision now resolves through the gate-policy resolver's
`plan_approval` toggle; the `plan_gate_auto_approves()` predicate
this ADR introduced has been removed. The `auto-plan` mode concept
is retained by the resolver's preset/overlay model.

## Context

`friction_level` (strict / guided / adaptive) is a single global axis
applied to every gate (`references/friction-levels.md`). The
`Dev10x:work-on` Phase 3 plan-approval gate and all downstream
decision gates resolve under the same level, which leaves one cell of
the (plan-gate × downstream-gate) matrix unreachable (GH-678):

| | downstream: auto-select | downstream: require decision |
|---|---|---|
| **plan: fire (veto preserved)** | `adaptive` | `guided` |
| **plan: skip (auto-approve)** | `solo-maintainer + adaptive` | **unreachable** |

A supervisor wanted the bottom-right cell: *"I trust your plan —
start. Wake me for the judgment calls."* Concretely — auto-approve the
plan (no babysitting the gate before branch checkout) while keeping
design forks, strategy/batch gates, and the Plan Completion Gate
firing.

GH-678 framed this as a *friction (pacing)* concern and floated three
options: (A) a new named `friction_level`; (B) per-gate-class
granularity (`friction_level: {plan: …, default: …}`); (C) a
decoupled `plan_approval: auto|gate` knob.

### Reconciling the observed plan-gate rule (AC#1)

`friction-levels.md` says `adaptive` auto-selects `(Recommended)`
gates without an `AskUserQuestion` interruption. The *observed*
work-on behavior is that the plan gate still **fires** under
`adaptive` (to preserve the supervisor's veto) **unless**
`solo-maintainer` is also active (GH-252), where it is bypassed
entirely. Both are intentional. The plan gate is therefore a
documented special case, and the canonical rule is now tabulated in
`references/friction-levels.md` § Plan-Approval Gate and encoded in
`dev10x.domain.session_rules.plan_gate_auto_approves()`.

## Decision

Express "trust the plan" as a **mode** (`active_modes: [auto-plan]`),
not as a new friction level or a new top-level knob.

Rationale for choosing a mode over GH-678's Options A/B/C:

- **`solo-maintainer` is the precedent.** It is already a mode that
  flips the *same* plan-approval gate (GH-252). A mode scoped to that
  one gate is consistent with existing behavior, reuses the
  `active_modes` machinery that work-on Phase 0/3 already reads and
  persists, and needs **no** `FrictionLevel` enum value,
  `command-skill-map.yaml`, or `skill_redirect.py` change (modes do
  not touch command redirection).
- **Composability** — `guided + auto-plan` reaches the previously
  unreachable cell; the mode composes with any friction level without
  re-deriving a matrix. This captures Option C's composability with
  zero new schema.
- **Bounded exception** — `auto-plan` flips exactly one gate. It does
  not generalise to per-gate pacing, so the "modes are structural,
  friction is pacing" orthogonality (`references/execution-modes.md`)
  stays intact for every other gate.

`auto-plan` auto-approves the Phase 3 plan-approval gate at **every**
friction level. Downstream decision gates, the Plan Completion Gate,
and `ALWAYS_ASK` gates all continue to resolve by `friction_level` —
the mode does not touch them.

`verify-acc-dod` is unaffected: it keys off `friction_level`, which
`auto-plan` does not change.

Walk-away precedence: when `walk_away: true` (`Dev10x:afk`) and
`auto-plan` are both set, walk-away (the stronger "I am gone" signal)
suppresses downstream non-destructive gates and logs them to the
`doubt_sink`; `auto-plan` still auto-approves the plan gate. Full
precedence is in `references/friction-levels.md` § Plan-Approval Gate.

## Consequences

- One new mode to document and one decision function
  (`plan_gate_auto_approves`) as the single source of truth, consumed
  by a SessionStart briefing (`BuildAutoPlanGuidanceRule`) that
  reinforces "plan auto-approved, downstream gates still fire" across
  compaction.
- The "modes are purely structural" taxonomy now has two documented
  gate-flipping exceptions (`solo-maintainer`, `auto-plan`). Both
  touch only the plan gate; the rule of thumb remains "pacing belongs
  on the friction axis" for every other gate.
- Options A and B from GH-678 are explicitly declined: A adds enum
  surface for one cell; B is the largest schema/parser change for
  flexibility no current use case needs. They remain available as
  future work if per-gate pacing is ever required.

## References

- GH-678 — the scoping issue this ADR resolves
- ADR-0002 — data-driven skill redirect with friction levels
- `references/friction-levels.md` § Plan-Approval Gate
- `references/active-modes.md` § `auto-plan`
- `references/execution-modes.md` § Gate-flipping modes
- `dev10x.domain.session_rules.plan_gate_auto_approves`
