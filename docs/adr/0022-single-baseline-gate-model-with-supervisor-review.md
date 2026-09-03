# 22. One baseline preset and one durable supervisor-review fact

Date: 2026-09-03

## Status

Accepted

Supersedes the three-preset shipped table in
[ADR-0016](0016-friction-gate-policy-presets-over-toggles.md) D-9/D-10
(`strict` / `guided` / `adaptive` → `adaptive` alone).

Amends [ADR-0019](0019-human-review-is-a-durable-project-fact.md):
`human_review` is renamed and generalised to
`supervisor_review: required | none`; its durable location, its
first-match-wins resolution, and its safety-floor semantics are retained
unchanged.

Does **not** touch
[ADR-0002](0002-data-driven-skill-redirect-with-friction-levels.md) —
see § "Out of scope: the ADR-0002 command-redirect axis".

Records the supervisor decision on
[GH-1157](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1157).

## Context

Dev10x carries two overlapping autonomy dials under one name.

- `gate_preset` (`strict` / `guided` / `adaptive`) selects one of three
  shipped toggle maps in `src/dev10x/domain/gate_policy.py`
  (`SHIPPED_PRESETS`).
- `friction_level` is both the pre-ADR-0016 alias for that *and* the
  independent ADR-0002 dial driving Bash command-redirect strictness
  (`config.friction_level` in
  `src/dev10x/validators/command-skill-map.yaml`, consumed by
  `skill_redirect.py`).

The name appears in roughly 70 files. Two unrelated questions —
"how much does the agent stop and ask?" and "how hard does the hook
push me from `gh pr create` toward the skill?" — answer to the same
word, and readers routinely conflate them.

Worse, the question an operator actually wants to answer — *does the
supervisor read the PR before the next step is allowed?* — is
expressible only indirectly, through five stacked layers:

1. pick a base preset (`strict` / `guided` / `adaptive`);
2. bolt on `solo-maintainer` / `afk` overlays;
3. pin individual toggles in `.dev10x/gate-policy.yaml`;
4. guard the overlays with `allowed_overlays` (ADR-0017);
5. set the `human_review` boolean (ADR-0019).

Five layers to express one fact is not configurability; it is a
combinatorial space in which most points are unreachable, several are
contradictory, and the operator cannot predict which one they are in.

Three further observations shaped the decision:

- **The base preset is not a session-time question.** In practice a
  supervisor does not pick `strict` on Tuesday and `adaptive` on
  Wednesday. Which gates fire is a property of the project and of
  whether a human is watching — and the second is what the overlays
  and `supervisor_review` already encode. `strict` and `guided`
  survived as artefacts of the pre-ADR-0016 three-level ladder, not
  because anyone chose between them.
- **`human_review` names the wrong actor.** ADR-0019 deliberately
  coupled "the team reviews here" and "the supervisor reviews here"
  into one boolean, on the grounds that they are the same fact. They
  are not. A solo repo has no team but may well want the supervisor to
  read the PR; a team repo may want the agent to hand straight to the
  team without a supervisor pass. Collapsing both into one boolean is
  what makes the four cells of the effect table below inexpressible.
- **AI self-review keeps getting proposed as a third dial.** Each
  friction discussion re-raises "should `Dev10x:review` on the agent's
  own branch be gateable?" It should not, and the absence of a written
  decision is why the question recurs.

## Decision

### D-1: `adaptive` is the sole shipped base preset

`strict` and `guided` are retired. There is no session-time autonomy
choice, and no widget that asks for one. **Auto-advance is the
baseline**: every gate resolves to its recommended option unless a
floor, a project pin, or a per-toggle override says otherwise.

The preset *mechanism* survives — `SHIPPED_PRESETS` keeps its shape,
user-defined presets in `~/.config/Dev10x/friction-presets.yaml` keep
working, and per-toggle overrides (ADR-0016 D-4) are untouched. What is
removed is the shipped *choice* between three postures and every
prompt, table, and doc paragraph that asked an operator to make it.

`adaptive`'s toggle values are unchanged from the ADR-0016 D-10 table's
right-hand column, including the author-keyed
`auto-advance-if-bot` values for `triage_response`,
`thread_resolution`, and `comment_hide`. Retiring the other two columns
retires no behaviour that `adaptive` had.

Consequently the ADR-0016 D-9 "net ladder" (guided = adaptive except
`request_review`, `merge`, `completion_signoff`) no longer describes
anything shipped. The behaviours it reached for — supervised team
interaction, no agent merge — are now reached through
`supervisor_review` and the existing project pins, at the tier where
repo character actually lives (ADR-0016 D-8).

### D-2: `supervisor_review: required | none` replaces the `human_review` boolean

`supervisor_review` is a **durable per-project fact** — a property of
the repo's shape and of how its owner works — **not a per-session
mood**. It answers exactly one question: *must the supervisor read this
PR before the next step is allowed?*

It lives where `human_review` lived: the global
`~/.config/Dev10x/friction.yaml`, keyed by the same first-match-wins
`projects[]` globs, resolved through the same `_policy_toplevel` seam.

```yaml
defaults:
  supervisor_review: required     # the safe default
projects:
  - match: ["*/my-solo-repo", "*/my-solo-repo-*"]
    supervisor_review: none
```

An enum rather than a boolean, because the two poles are *states of the
project*, not a negation of one another, and because a future third
value (e.g. `sampled`) has somewhere to go. Absent, unrecognised, or
malformed values read as **`required`** — every unconfigured repo keeps
today's behaviour and every typo fails toward more oversight, exactly
as ADR-0019 specified for `human_review`.

### D-3: The effect point moves with repo shape

`supervisor_review` does not have one effect; it has one *meaning* with
two effect points, selected by whether the repo is solo or team-shaped.
This table is the contract:

| repo | `supervisor_review` | Behaviour |
|---|---|---|
| solo | `none` | AI self-review → CI → agent merges |
| solo | `required` | AI self-review → CI → **park for supervisor** → merge |
| team | `none` | AI self-review → CI → agent requests team review |
| team | `required` | AI self-review → CI → **park for supervisor** → then request team review |

Reading the table:

- **AI self-review and CI always come first**, in all four cells. They
  are not gated (D-4) and their findings are addressed before any human
  is asked to look at anything. The supervisor is never handed a PR the
  agent has not already reviewed and greened.
- **`required` inserts a park, it never removes a step.** In the team
  rows it does not replace the team review request; it precedes it. The
  supervisor pass and the team pass are different acts by different
  people.
- **`none` does not mean "nobody reviews".** In the team rows the team
  still reviews; the agent simply does not stop for the supervisor
  first.
- **Repo shape is not a new key.** Solo vs team is already expressed by
  the existing configuration surface — the `solo-maintainer` overlay,
  the git-tracked `.dev10x/gate-policy.yaml` `request_review` /
  `merge` pins (ADR-0016 D-8), and `merge_config.solo_maintainer`. This
  ADR adds no shape discriminator; it states what `supervisor_review`
  means against the shape already declared.

The four cells are precisely what a single `human_review` boolean could
not express, because it conflated the actor in the solo rows with the
actor in the team rows.

### D-4: AI self-review is NOT a policy axis and always auto-advances

**`Dev10x:review` on the agent's own branch always runs and always
auto-advances. It is not gateable, not preset-dependent, not
overlay-dependent, and not a toggle.** No configuration surface may
expose it.

This is recorded as an explicit decision, not an aside, so that a later
implementer does not "helpfully" make it configurable, and so the
recurring question has a written answer to point at.

The reasoning: a gate exists to route a decision to a human whose
judgement or accountability is required. Self-review consumes no human
attention, has no social dimension, is idempotent, and its output is
findings — not actions. Making it optional buys nothing (it costs the
supervisor no time) and risks the one thing the whole model depends on:
that every cell of the D-3 table starts from a reviewed branch. A
"skip self-review" switch is a switch for shipping unreviewed code, and
there is no posture in which that is the right default.

`Dev10x:review-fix`'s downstream behaviour is likewise unchanged; the
`autofix_confidence` weight continues to govern which findings are
auto-sent, as it does today.

### D-5: The floor mechanism survives — `required` is a precondition, never a grant

`supervisor_review: required` is expressed as a **safety floor**, in the
same `_floors()` mechanism that carries `human_review` today. A floor
can only ever force `ask`; it can never grant `auto-advance`.

This preserves the GH-1000 invariant exactly:

- The value is read **unconditionally** from the durable prefs through
  `_policy_toplevel`. A caller-supplied
  `context={"supervisor_review": "none"}` is dropped into
  `ignored_context_fields`, as `human_review` is today. Durable project
  policy must not have two answers, and an unattended agent must not be
  able to self-authorise its way past the supervisor.
- `supervisor_review: none` is a **precondition** for agent merge
  autonomy, not a grant of it. The independent vetoes of ADR-0019 all
  still stand and any one of them can withhold autonomy:
  - the git-tracked `.dev10x/gate-policy.yaml` `merge: ask` pin
    (ADR-0016 D-8);
  - `allowed_overlays` (ADR-0017), which still drops `solo-maintainer`
    before gate resolution — `supervisor_review` is not an overlay and
    does not re-admit one;
  - `merge_config.solo_maintainer`, which governs the
    `Dev10x:gh-pr-merge` approval override independently.

Both must agree; either can veto. Nothing about D-1's collapse to a
single baseline weakens this — retiring `strict` removes a posture that
asked *more*, and the floors are what continue to supply "ask" where it
is genuinely needed. The ADR-0016 safety-floor list (secret access,
destructive-irreversible operations, cross-author pushes, privacy
disclosure, blocking-class escalations) is unchanged and remains
preset-independent, which is why a single baseline is safe.

### D-6: The `afk` overlay is untouched

`afk` composes `session_adoption`, `external_notify` queueing, and
`doubt_sink` — facts about whether a human is present to answer a
widget at all. Those are orthogonal to *who reviews the PR*, which is
what `supervisor_review` answers. The overlay keeps its current
definition and its current composition semantics.

`solo-maintainer` likewise remains an overlay. It expresses repo shape,
which D-3 reads; it is not replaced by `supervisor_review`.

### Out of scope: the ADR-0002 command-redirect friction axis

**The ADR-0002 command-redirect axis is a separate dial and is out of
scope for this ADR.** It is `config.friction_level` in
`src/dev10x/validators/command-skill-map.yaml`, consumed by
`skill_redirect.py`, and it governs how hard the PreToolUse Bash hook
pushes an agent from a raw CLI command toward its skill wrapper
(`block` / `warn` / `off`-shaped strictness on ~12 command families).

It is a **different question with a different subject**: it constrains
the *agent's tool choice*, not the *supervisor's involvement*. Nothing
in this ADR changes it, renames it, or collapses it into
`gate_preset` / `supervisor_review`.

This boundary is stated explicitly because the shared word
`friction_level` is precisely what invites the collapse. Any future
work that touches the redirect axis must justify itself on redirect
grounds, not by analogy to the gate model. That axis is being decided
separately in
[GH-1158](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1158),
which is deliberately independent of this ADR's dependency chain and
blocks nothing here.

## Alternatives Considered

### Alternative A — keep three presets, add a fourth for the missing posture

The status-quo trajectory: each audit that finds an inexpressible
posture adds a preset column.

**Pros:** smallest diff; no rename; existing docs stay valid.
**Cons:** the D-3 table has four cells and the presets have three
columns, so the mismatch is structural — a fourth column does not fix
it, it just moves the next collision. The preset axis and the
review-actor axis are genuinely different questions; multiplying one
to cover the other is what produced the five-layer stack in the first
place.
**Verdict:** Rejected — carve-out debt grows per audit, exactly as
ADR-0016 alternative 2 predicted.

### Alternative B — keep `human_review`, document the four cells against it

Leave ADR-0019's boolean in place and specify solo/team behaviour in
prose.

**Pros:** no rename, no migration, no code change.
**Cons:** the boolean has two poles and the table has four cells, so
two of them would have to be inferred from repo shape without the flag
saying anything about them — which is exactly the ambiguity that made
"does the supervisor read this PR?" unanswerable. And the name would
keep pointing at "humans" generally while meaning "the supervisor
specifically" in half the table.
**Verdict:** Rejected — the rename *is* the decision; the boolean's
name is the defect.

### Alternative C — make AI self-review a toggle for symmetry

Add `self_review` to the toggle map so every review step is
configurable through one uniform surface.

**Pros:** uniform; no special case in the resolver; satisfies the
instinct that anything gate-shaped should be tunable.
**Cons:** it is a switch whose only reachable effect is shipping
unreviewed code. Self-review costs no human attention, so there is no
friction to relieve — the toggle would exist purely as a footgun, and
every cell of D-3 assumes a reviewed branch as its starting point.
**Verdict:** Rejected — and recorded as D-4 precisely so it is not
re-proposed.

### Alternative D — collapse the ADR-0002 redirect axis into this model

One `friction_level` to rule both, eliminating the name collision by
unification rather than by boundary.

**Pros:** kills the ambiguity at the root; one word, one meaning.
**Cons:** the two dials have different subjects (supervisor
involvement vs agent tool choice), different consumers (gate resolver
vs PreToolUse hook), and different failure modes (unreviewed merge vs
raw-CLI drift). Unifying them means every future change to one has to
argue about the other.
**Verdict:** Rejected — the ambiguity is resolved by naming the
boundary (§ Out of scope) and by GH-1158 deciding the redirect axis on
its own terms.

## Consequences

### What becomes easier

1. **One question, one answer.** "Does the supervisor read this PR?"
   is one key in one file, and the D-3 table says exactly what follows.
2. **The five-layer stack collapses to two.** Repo shape (already
   declared) plus `supervisor_review`. No base-preset pick, no posture
   widget, no reasoning about which of three columns a session is in.
3. **The four postures are all reachable.** Including "solo repo,
   supervisor still reads it" and "team repo, hand straight to the
   team" — neither expressible before.
4. **Docs shrink.** Every three-column preset table, every
   strict-vs-guided-vs-adaptive comparison, and every "pick your
   friction level" prompt goes away.
5. **Self-review is settled.** A written decision to point at ends the
   recurring proposal.

### What becomes more difficult

1. **`strict` is gone.** A supervisor who wanted every gate to fire no
   longer has a one-word way to ask for it. This is intended: the
   floors supply "ask" where it is genuinely needed, and
   `supervisor_review: required` supplies it at the review boundary.
   Anyone who wants more than that can still pin individual toggles —
   the per-toggle override mechanism is deliberately retained.
2. **Migration touches the ~70 files carrying the old name**, plus the
   `human_review` reader, the `_floors()` entry, `human_review_status`,
   and the shipped preset files. Sequenced across FRIC-M2/M3/M4; this
   ADR is the gate on all of it.
3. **Repo shape is read, not declared.** D-3 keys on a shape expressed
   across three existing surfaces rather than one field. Deliberate —
   adding a fourth way to say "solo" would re-grow the stack this ADR
   collapses — but it means the shape must be read consistently by
   every consumer of the table.

### Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| A repo relying on `strict` silently loses gates on upgrade | Medium | High | `supervisor_review` defaults to `required`, so the review boundary holds; safety floors are preset-independent; legacy `strict` maps to `adaptive` + `supervisor_review: required` |
| `supervisor_review: none` set casually on a team repo | Medium | Medium | `none` is a precondition, never a grant — `merge: ask` pins and `allowed_overlays` remain independent vetoes (D-5) |
| Malformed value (`"no"`, `false`, `"None"`) read as `none` | Low | High | Only the exact literal `none` disables the park; anything else reads as `required` |
| A later implementer makes self-review configurable | Medium | High | D-4 records it as an explicit decision with its reasoning; Alternative C records the rejection |
| The two `friction_level` axes get collapsed by a future refactor | Medium | Medium | § Out of scope states the boundary; GH-1158 decides the redirect axis independently |

## References

### Internal

- [GH-1157](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1157) —
  the two-overlapping-dials problem and the supervisor decision this
  ADR records; root of the FRIC-M2/M3/M4 dependency chain
- [GH-1158](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1158) —
  the ADR-0002 command-redirect axis, decided separately
- [GH-1000](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1000) —
  the unconditional-read / `ignored_context_fields` invariant preserved
  by D-5
- [GH-950](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/950) —
  `human_review`'s origin as a durable project fact
- [ADR-0002](0002-data-driven-skill-redirect-with-friction-levels.md) —
  the command-redirect friction axis; explicitly out of scope here
- [ADR-0016](0016-friction-gate-policy-presets-over-toggles.md) — the
  gate resolver, toggle taxonomy, safety floors, and the D-9/D-10
  three-preset table this ADR supersedes
- [ADR-0017](0017-durable-mode-guard-policy-is-local-not-git-tracked.md)
  — `allowed_overlays` overlay guard, retained as an independent veto
- [ADR-0018](0018-session-state-relocates-out-of-project-claude-tree.md)
  — nothing durable under a repo's `.claude/`
- [ADR-0019](0019-human-review-is-a-durable-project-fact.md) —
  `human_review`, amended here: renamed and generalised, floor
  semantics retained
- `src/dev10x/domain/gate_policy.py` — `SHIPPED_PRESETS`,
  `SHIPPED_OVERLAYS`, `GateContext`, `_floors()`
- `src/dev10x/validators/command-skill-map.yaml` — the separate
  ADR-0002 `config.friction_level` dial
