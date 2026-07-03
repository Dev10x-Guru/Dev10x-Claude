# ADR-0016: Friction Gate Policy — Presets over Toggles with a Resolver Tool

- **Status:** Proposed
- **Date:** 2026-07-03
- **Roots:** GH-742, GH-743, GH-744, GH-745 (skill-audit 2026-07-01)
- **Supersedes (partially):** the three-level `friction_level` contract in
  [ADR-0002](0002-data-driven-skill-redirect-with-friction-levels.md) and the
  gate-flipping-mode exception in
  [ADR-0014](0014-auto-plan-mode-for-plan-approval-gate.md)

## Context

Four audit issues from a single week converged on the same defect: the
autonomy/gating model is too coarse, and its levers are entangled.

- **GH-742** — a stale `session.yaml` carrying `solo_maintainer: true`
  was silently adopted by a new invocation and auto-merged PR #740 with
  no human review. There is no named setting between "full autonomy
  including merge" and "every gate fires".
- **GH-743** — `Dev10x:afk` hard-codes `active_modes: [solo-maintainer]`
  as its walk-away invariant, conflating "run autonomously" with "merge
  autonomously"; it appends modes instead of reconciling them; and
  friction settings are too coarse to express "trust the plan, keep
  working, don't merge".
- **GH-744** — `walk_away` (gate suppression) and `solo-maintainer`
  (reviewer/merge structure) are orthogonal but coupled in the afk
  skill; no warning fires when oversight modes coexist with adaptive.
- **GH-745** — auto-advance cannot key on review-comment **author
  type**: bot-authored threads (safe to handle autonomously) and
  human-authored threads (a trust/social act requiring supervisor
  sign-off) are treated identically. Batch gates block even when a
  batch produces zero VALID fixups.

A three-agent sweep enumerated **~75 documented decision gates across
40+ skills** (explicit `AskUserQuestion` calls plus implicit
preview/confirm pauses). They collapse into 18 gate classes. Today each
skill reads `friction_level` + `active_modes` + `walk_away` and
re-derives gate behavior in prose, producing drift (three separate
documents define precedence), unreachable postures (AFK-without-merge),
and stale-file hazards.

The current model's levers:

| Layer | Controls |
|-------|----------|
| `friction_level` (strict/guided/adaptive) | how a fired gate resolves |
| `active_modes` (structural + 2 gate-flipping exceptions) | what steps exist |
| `walk_away` + `doubt_sink` | whether non-destructive gates fire at all |

A DDD workshop (2026-07-03) modeled the domain and the supervisor
directed the design through eight decisions (D-1..D-8 below).

## Decision

### D-1: `friction_level` becomes a policy preset

The three levels survive as **shipped presets** — named value-maps over
fine-grained toggles — not as a special enum skills branch on. Users
can define additional presets.

### D-2: Skills are policy-ignorant; a resolver tool answers per gate

Skills never read `friction_level`, `active_modes`, or `walk_away`.
At each decision gate the skill calls one MCP tool:

```
mcp__plugin_Dev10x_cli__resolve_gate(
    gate="thread_resolution",
    context={"author_type": "bot", "destructive": false,
             "overlap_signals": 2, "confidence": 85,
             "valid_fixup_count": 0})
→ {"effect": "auto",                  # ask | auto | skip
   "resolved_option": "Recommended",
   "log_to": "pr-description",
   "reason": "preset:adaptive thread_resolution=auto_if_bot author=bot",
   "floors_applied": []}
```

Domain logic lives in `dev10x.domain.session_rules` (which already
centralizes `plan_gate_auto_approves()` and
`completion_gate_recommendation()` — both become internal to the
resolver). The MCP boundary routes through `to_wire()` per ADR-0009.

![resolve_gate resolution pipeline](diagrams/0016/resolve-gate-sequence.png)

### D-3: Toggles are typed — bool, enum, weight

22 toggles derived from the gate inventory. Effects vocabulary (D-6):
`ask` (fire, block) / `auto` (resolve to recommended, never block) /
`skip` (structural removal). Conditional autos: `auto_if_bot`,
`auto_if_safe`, `auto_if_merged`, `auto_if_stale_free`. Weights are
numeric thresholds feeding conditional autos.

| Toggle | Type | Values |
|---|---|---|
| `plan_approval` | enum | ask / auto |
| `batch_layout` | enum | ask / auto (weight-conditioned) |
| `strategy_choice` | enum | ask / auto |
| `artifact_preview` | enum | ask / auto |
| `triage_response` | enum | ask / auto_if_bot / auto |
| `thread_resolution` | enum | ask / auto_if_bot / auto |
| `comment_hide` | enum | ask / auto |
| `yagni_routing` | enum | ask / auto |
| `shipping_continuation` | enum | ask / auto |
| `request_review` | enum | ask / auto / skip |
| `external_notify` | enum | ask / auto / skip |
| `merge` | enum | ask / auto |
| `completion_signoff` | enum | ask / auto |
| `history_rewrite` | enum | ask / auto_if_safe / auto |
| `workspace_choice` | enum | ask / auto |
| `branch_cleanup` | enum | ask / auto_if_merged / auto (D-5) |
| `session_adoption` | enum | ask / auto_if_stale_free / auto |
| `zero_valid_autoflow` | bool | batch gates auto-advance on zero VALID fixups |
| `autofix_confidence` | weight | 0–100; review-fix auto-sends findings ≥ threshold |
| `batch_ambiguity_floor` | weight | min overlap signals to auto-accept a batch |
| `doubt_sink` | enum | pr-description / session-bookmark / commit-footer |
| `anchor_recommendations` | bool | show "(Recommended)" anchoring in ask widgets |

`auto_if_bot` encodes the GH-745 author-type rule: bot-authored threads
resolve autonomously; human-authored threads escalate to `ask`
regardless of preset.

### D-4: Per-toggle session override

Any single toggle can be overridden for the current session without
changing the preset. Resolution order (lowest to highest):

```
plugin preset < project override < session preset choice
             < per-toggle session override < safety floors
```

### D-5: Reversibility decides floor vs toggle

Reversibility is tri-state (trivial / assisted / none). Only
*none*-tier operations are floors. Branch deletion is
assisted-recoverable (reflog) → the `branch_cleanup` toggle with
`auto_if_merged` (auto-delete only branches whose tips are reachable
from base). Mass delete of untracked files, worktree removal holding
uncommitted work → floors.

### D-6: Two effects; anchoring is display, not effect

`recommend` is eliminated: today's strict-vs-guided difference is
anchoring bias in the widget, not behavior. `anchor_recommendations`
(bool, preset-level) captures it honestly.

### D-7: `auto` is never silent

Every auto-resolution MUST surface a visible one-line record in the
session transcript — `⚙ gate:<toggle> auto → "<option>" (<reason>)` —
so a present supervisor can notice and override mid-flight, AND append
to the audit log + `doubt_sink`. An auto-resolution without a visible
record is a compliance bug (extends walk-away.md's silent-suppression
anti-pattern to the whole resolver).

### D-8: Merge is auto at adaptive; the human boundary lives at the project tier

`adaptive` IS the walk-away autonomy posture, merges included. The
team-repo human boundary is a **project-tier concern**: a team-reviewed
repo pins `merge: ask` (and typically `external_notify: ask`) in its
project config. Because project overrides outrank the preset, adaptive
sessions on that repo still stop for a human merge while solo repos
merge autonomously. Repo character (solo vs team) is a durable property
of the repo — encoding it per-project kills the GH-743/744 failure mode
at the right layer, and a stale session file can no longer cross the
boundary (D-8 composes with `session_adoption: auto_if_stale_free`,
which re-prompts when `session.yaml` mismatches the current
invocation — GH-742 F1).

### Shipped presets

| Toggle | strict | guided | adaptive |
|---|---|---|---|
| plan_approval | ask | ask | auto |
| batch_layout | ask | ask | auto |
| strategy_choice | ask | ask | auto |
| artifact_preview | ask | ask | auto |
| triage_response | ask | ask | auto_if_bot |
| thread_resolution | ask | ask | auto_if_bot |
| comment_hide | ask | ask | auto |
| yagni_routing | ask | ask | auto |
| shipping_continuation | ask | ask | auto |
| request_review | ask | ask | auto |
| external_notify | ask | ask | ask |
| merge | ask | ask | auto |
| completion_signoff | ask | ask | auto |
| history_rewrite | ask | ask | auto_if_safe |
| workspace_choice | ask | ask | auto |
| branch_cleanup | ask | ask | auto_if_merged |
| session_adoption | ask | auto_if_stale_free | auto_if_stale_free |
| zero_valid_autoflow | 0 | 0 | 1 |
| autofix_confidence | 101 (never) | 70 | 70 |
| batch_ambiguity_floor | ∞ (always ask) | 3 | 3 |
| anchor_recommendations | false | true | true |

Overlay presets (patches on a base): `solo-maintainer`
(request_review: skip, external_notify: skip, merge: auto at any base)
and `afk` (session_adoption: auto, external_notify queued to
doubt_sink, doubt_sink: pr-description). The afk skill composes
presets instead of appending `solo-maintainer` to `active_modes`
(GH-743 F1, GH-744 F2); conflicting oversight configuration is
reconciled by preset replacement.

### Safety floors (deny-overrides)

The resolver returns `ask` regardless of preset or override for gates
with no blind-pickable safe default:

- **Secret access** — aws-vault retrieval incl. read-only lookups
- **Destructive-irreversible** (reversibility: none) — force-push to
  protected branches; mass delete of untracked files; worktree removal
  holding uncommitted work
- **Cross-author pushes** — courtesy-fixup to another author's branch
- **Privacy disclosure** — unfictionalizable audit findings
- **Blocking class** — missing credentials / MCP unreachable;
  unresolved merge or directive conflicts; BLOCKED-item escalations;
  gh-pr-merge override gates (merge despite infra-red CI,
  admin-override a review block)

## Alternatives Considered

1. **Single named mode (`afk-autonomous`) added to `active_modes`** —
   least churn; but leaves the human boundary and author-type keying
   implicit/hardcoded, does not deliver GH-743 F3's per-gate
   granularity, and each skill still re-derives gate behavior from
   prose. Rejected: treats the symptom, not the entanglement.
2. **Keep three-level friction, add carve-outs per audit finding** —
   the status quo trajectory (GH-252, GH-678, GH-808 each added a
   carve-out). The precedence prose already spans three documents and
   contradicts itself at the plan gate. Rejected: carve-out debt grows
   per audit.
3. **Per-gate-class policy WITHOUT a resolver tool** (skills read the
   toggle map themselves) — same taxonomy, but every skill re-implements
   resolution order, floors, and logging; drift returns within a few
   releases. Rejected: the tool is what makes skills policy-ignorant
   and the contract testable in one place.
4. **Three effects (ask / notify / auto)** with `notify` =
   fire-and-proceed (widget emitted, agent proceeds on recommended if
   not overridden) — genuinely distinct middle ground with precedent in
   the plan gate at adaptive; deferred, not adopted: D-7's visible
   auto-records cover the "supervisor can notice and override" need
   with less harness complexity. Revisit if auto-records prove too easy
   to miss.

## Consequences

**Easier:**
- "AFK but don't merge on team repos" is expressible and durable
  (project tier), closing GH-742 F2, GH-743 F1/F3, GH-744 F2.
- Bot/human author keying is first-class (GH-745 F4);
  zero-VALID batches auto-flow (GH-745 F1).
- One resolution pipeline, one precedence order, unit-testable; the
  scattered prose rules (walk-away flowchart, plan-gate matrix,
  adaptive carve-outs) collapse into `session_rules`.
- Skill migration shrinks skill docs: `ALWAYS_ASK` markers become
  floors in the resolver, not repeated prose.
- Every autonomous decision is visible and auditable (D-7).

**Harder / risks:**
- Migration touches every gate-emitting skill (~40). Mitigated by
  phased rollout (below) — the resolver defaults to current behavior
  for unmigrated skills, which keep reading session.yaml until
  converted.
- A per-gate MCP call adds latency at each gate. Mitigated: resolution
  is a pure in-process lookup behind a long-lived server (~ms), and
  gates are seconds-scale interactions.
- `session.yaml` schema changes (preset + toggle overrides replace
  friction_level/active_modes/walk_away). Mitigated by 1:1 legacy
  mapping (`adaptive` → preset adaptive; `solo-maintainer` → overlay;
  `walk_away: true` → afk overlay) read-compatible in the resolver.
- Two knob surfaces during transition (modes for structural behavior,
  toggles for gates). `active_modes` remains for purely structural
  modes (`review-deferred`, `swarm-child`); the gate-flipping
  exceptions (`solo-maintainer`, `auto-plan`) migrate into overlays,
  retiring ADR-0014's exception.

## Implementation Plan

Phase 1 (this PR, spike): `dev10x/domain/session_rules.py` —
`resolve_gate()` pipeline (preset → overlay → session override →
conditional-context → floors), preset definitions, legacy
session.yaml mapping; unit tests replaying the four audit scenarios
(stale-config auto-merge, bot-vs-human thread, team-repo project pin,
zero-VALID batch). MCP tool `resolve_gate` on the `cli` server via
`to_wire()`; row added to `.claude/rules/mcp-tools.md`.

Phase 2: migrate gate-heavy skills — work-on (plan/batch/strategy/
completion), gh-pr-respond (G1–G7), gh-pr-merge, git-commit,
gh-pr-monitor — replacing session.yaml reads with `resolve_gate` calls.
Rewrite `Dev10x:afk` as preset composition.

Phase 3: long-tail skills; update `references/friction-levels.md`,
`references/execution-modes.md`, `references/walk-away.md`,
`references/active-modes.md` to defer to the resolver; deprecate
`walk_away` key.

Phase 4: close GH-742/743/744/745 findings not already covered
(gh-pr-respond merge-state preamble GH-744 F1, `check_top_level_comments`
broadening GH-743 F2, git-commit unattended detection GH-745 F2 —
mechanical fixes reshaped to consume the resolver).

## Open Questions (resolved defaults)

- **Unknown author type** → treated as `human` (safe direction).
- **Preset files** → plugin ships `presets/friction/*.yaml`; user
  presets in `~/.config/Dev10x/friction-presets.yaml`; session pick +
  per-toggle overrides in `.claude/Dev10x/session.yaml`.

## References

- Workshop artifact: DDD session 2026-07-03 (D-1..D-8), gate inventory
  sweeps (75 gates, 18 classes)
- GH-742, GH-743, GH-744, GH-745 — audit-2026-07-01 findings
- ADR-0002 (friction levels), ADR-0009 (Result contract at MCP
  boundary), ADR-0014 (auto-plan mode — exception retired by this ADR)
- Cedar policy language (permit/forbid + deny-overrides) — floor
  semantics inspiration, per the GH-271 PAP scoping
