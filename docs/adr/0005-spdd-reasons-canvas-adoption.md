# ADR 0005 — Adopt SPDD REASONS Canvas patterns into Dev10x scoping

**Status:** Accepted (2026-05-16)
**Context:** GH-70, GH-169, GH-170, GH-171, GH-172, GH-173, GH-174, GH-175
**Related:** ADR 0001 (skill-instruction trust), `Dev10x:scope`,
`Dev10x:ticket-scope`, `Dev10x:adr`, `Dev10x:jtbd`,
`references/skill-pipelines.md`

## Context

Martin Fowler's
[Structured Prompt-Driven Development](https://www.martinfowler.com/articles/structured-prompt-driven/)
(SPDD) proposes a seven-part **REASONS Canvas** as the
single, version-controlled artifact that drives spec → code →
tests:

| SPDD layer    | Concern                                                  |
|---------------|----------------------------------------------------------|
| **R**equirements | Who needs the change, what they need, and why         |
| **E**ntities     | Domain objects, properties, relationships             |
| **A**pproach     | Architectural style, libraries, frameworks            |
| **S**tructure    | Modules, components, layering, boundaries             |
| **O**perations   | API endpoints, events, workflows, command shapes      |
| **N**orms        | Project conventions: style, naming, testing rules     |
| **S**afeguards   | Invariants, validations, security, error handling     |

SPDD also defines a **Golden Rule** — *"fix the prompt first,
then the code"* — and ships `spdd-prompt-update` /
`spdd-sync` commands that regenerate the spec whenever code
drifts.

Dev10x already produces most of the same content through
several skills, but the outputs are scattered across
artifacts, the governance layers (Norms, Safeguards) are
implicit in `.claude/rules/` and `CLAUDE.md` rather than
travelling with the ticket prompt, and there is no living spec
that gets re-synced when code drifts. GH-70 asks whether to
adopt parts of SPDD and, if so, how.

### Current Dev10x coverage (audited)

| SPDD layer  | Current Dev10x output                          | Source skill(s)                              | Coverage |
|-------------|------------------------------------------------|----------------------------------------------|----------|
| Requirements | Job Story (1 sentence) + Objective / AC       | `Dev10x:jtbd`, `Dev10x:ticket-scope`         | ✅ Full   |
| Entities    | "Models / DTOs" bullets under Architecture     | `Dev10x:ticket-scope` templates              | ⚠️ Partial — no relationships, no property schema |
| Approach    | Technical Approach + Design Discussion + Alts  | `Dev10x:scope`, `Dev10x:adr`                  | ✅ Full   |
| Structure   | Architecture > Components, Clean-arch layering | `Dev10x:scope`, `Dev10x:ticket-scope`, ADR   | ✅ Full   |
| Operations  | Implementation Steps, GraphQL Changes, API     | `Dev10x:ticket-scope` templates              | ✅ Full   |
| Norms       | `.claude/rules/essentials.md`, `CLAUDE.md`     | (project rules — *not* on the ticket prompt) | ❌ Gap — implicit only |
| Safeguards  | Risks + Mitigations                            | `Dev10x:scope`, `Dev10x:adr`                  | ⚠️ Partial — defensive only, no first-class invariants/validations |

### Gaps SPDD highlights

1. **No living spec.** Scope docs are written once and not
   re-generated; the ticket-scope output lives at
   `/tmp/Dev10x/ticket-scope/<ID>-scope.md` (volatile) and the
   PR description is the closest persistent artifact.
2. **Norms travel out-of-band.** Generation prompts inherit
   project rules through CLAUDE.md auto-load, but Norms are
   never re-stated inside the ticket spec, so a fresh
   `Dev10x:work-on` session that compacts CLAUDE.md (or runs
   in a worktree with diverging rules) can drift.
3. **Safeguards are reactive.** "Risks + Mitigations" answer
   *what could go wrong*; SPDD's Safeguards answer *what must
   always hold true* (invariants the implementation and the
   tests both check).
4. **Entities are under-modelled.** Templates list models and
   DTOs by name but do not capture property names, types, or
   relationships — exactly the part LLMs hallucinate most
   often during generation.
5. **No drift detection.** There is no `Dev10x:spec-update`
   (logic changes: edit spec → regenerate) or
   `Dev10x:spec-sync` (refactors: edit code → update spec).
   `Dev10x:gh-pr-respond` and `Dev10x:git-groom` do not check
   for spec drift.

## Decision

Adopt SPDD selectively in three layers, ordered by ROI:

### Layer 1 — Extend `Dev10x:scope` and ticket-scope templates (in-scope)

Add three sections to the three ticket-scope templates
(`business-feature`, `technical-task`, `bug-fix`) so every
saved scope already covers all seven REASONS dimensions:

| New section          | SPDD layer  | Populated from                                     |
|----------------------|-------------|----------------------------------------------------|
| `## Entities`        | Entities    | Models/DTOs expanded with property+relationship table |
| `## Norms`           | Norms       | Auto-rendered from `.claude/rules/essentials.md` + project rules matched to changed paths |
| `## Safeguards`      | Safeguards  | Invariants + validation rules (separate from `## Risks`) |

The `## Risks` section stays — it answers a different
question ("what could go wrong during rollout") than
Safeguards ("what must always be true post-change").

### Layer 2 — Add two new skills (proposed, separate tickets)

| New skill             | Trigger                                           | Behaviour |
|-----------------------|---------------------------------------------------|-----------|
| `Dev10x:spec-update`  | Logic change: requirements / behaviour shift     | Edit spec first, regenerate code via `Dev10x:work-on` |
| `Dev10x:spec-sync`    | Refactor: code shape changes but behaviour stable | Diff code against spec, update spec to match |

Wire them into `Dev10x:gh-pr-respond` (catch drift at review)
and `Dev10x:git-groom` (catch drift at merge). The spec is
the saved ticket-scope document promoted to a tracked path
(`docs/specs/<TICKET-ID>.md` — proposed) once approved.

### Layer 3 — `work-on` integration (proposed, separate ticket)

Add a `structured-spec` play to `Dev10x:work-on` mirroring
SPDD's six-step pipeline on top of existing skills:

```
ticket-scope (with REASONS) → adr (if architectural)
  → spec-update gate → implement → py-test (API)
  → py-test (unit) → spec-sync gate before merge
```

Keep `work-on`'s adaptive routing so simple changes
(`local-only`, `bugfix` with obvious root cause) skip the
structured pipeline. Borrow SPDD's "poor fit" list —
exploratory spikes, one-off scripts, single-file tweaks — as
a suitability gate in Phase 1 classification.

### Skill structure: extend vs. new skill

**Recommendation: extend, do not create `Dev10x:reasons-canvas`.**

Reasons:

- `Dev10x:scope` already runs the seven dimensions across its
  Phases 1–4; the missing pieces are *template sections*, not
  *workflow steps*. A new skill would duplicate scope's
  context-gathering and Design-It-Twice phases.
- Three saved templates already exist
  (`business-feature-template.md`, etc.). Adding three
  sections is a focused change with a known blast radius.
- The Norms/Safeguards autopopulator is a small renderer, not
  a skill. It can live as a helper called by the templates.
- The two genuinely net-new behaviours
  (`Dev10x:spec-update` / `Dev10x:spec-sync`) are *separate*
  from canvas authoring — they're drift management. They
  deserve their own skills regardless of how the canvas is
  produced.

## Alternatives Considered

### Alternative 1 — New `Dev10x:reasons-canvas` skill

Create a standalone skill that produces the seven-section
canvas as a fresh artifact.

- **Pros:** Clean separation from existing scope; SPDD
  vocabulary preserved 1:1; easier to swap out later.
- **Cons:** Duplicates 70% of `Dev10x:scope` (Phases 1–3 are
  already context gathering + Approach + Structure); creates
  two scoping skills users have to choose between; the
  templates already exist and downstream consumers (PR
  creation, project audit) depend on them per GH-28.
- **Verdict:** Rejected as the primary path. Reconsider only
  if Layer-1 template extensions prove insufficient.

### Alternative 2 — Adopt the `openspdd` CLI directly

Wrap SPDD's reference CLI as MCP tools and call them from
work-on.

- **Pros:** Zero re-implementation; benefits from upstream
  updates.
- **Cons:** Dev10x has its own skill runtime, hook system,
  and friction-level model — wrapping a CLI bypasses all of
  it. Out-of-scope per GH-70 explicitly.
- **Verdict:** Rejected. GH-70 says *"map concepts, not the
  tool"*.

### Alternative 3 — Norms/Safeguards as a `.claude/rules/` file only

Add `rules/spdd-norms.md` and `rules/spdd-safeguards.md` and
let CLAUDE.md auto-loading carry them.

- **Pros:** Zero work.
- **Cons:** Doesn't solve the gap. Rules are already
  auto-loaded — the problem is they don't *travel with the
  ticket spec*, so a compacted session, a worktree fork, or
  a different agent loses them. SPDD's insight is that the
  spec is the prompt; the rules must be *inside* it.
- **Verdict:** Rejected.

## Consequences

### Easier

- Every scoping doc now self-contains the constraints
  (Norms, Safeguards) needed for fresh generation — no
  reliance on session context.
- `Dev10x:work-on` agents (especially fanout swarm children
  per ADR 0004) can act on a spec without re-fetching project
  rules.
- Spec drift becomes detectable at review (`gh-pr-respond`)
  and merge (`git-groom`) instead of discovered post-merge.
- The Entities section gives generation prompts a typed
  vocabulary, reducing field-name hallucinations.

### Harder

- Template surface grows by three sections × three templates
  = 9 new section blocks. The Norms autopopulator has to
  match changed paths to relevant rule files (path-aware
  routing already exists in `.claude/rules/INDEX.md` — reuse
  that).
- `spec-update` / `spec-sync` need a canonical spec location.
  Promoting from `/tmp/Dev10x/ticket-scope/` to
  `docs/specs/<TICKET-ID>.md` changes the lifecycle: specs
  become committed artifacts. Some tickets won't justify a
  committed spec; the Phase-1 suitability gate keeps the
  pipeline opt-in.

### Risks

- **Template inflation.** Adding three sections to every
  scope may discourage scoping for small tickets. Mitigation:
  the suitability gate (SPDD's "poor fit" list) skips the
  structured pipeline for tickets that don't earn it.
- **Norms autopopulator drift.** If the rendered Norms
  section copies stale rule text, the spec lies. Mitigation:
  render at *generation* time, not at scope-save time —
  re-render whenever the spec is fed into a generation
  prompt.
- **Two-skill drift.** `spec-update` and `spec-sync` could
  diverge on what "spec drift" means. Mitigation: share a
  diff helper module; one canonical drift detector, two
  entry points.

## Implementation Plan

Each item below becomes a separate follow-up ticket. This ADR
records the *decision*; the tickets carry the work.

| #      | Ticket  | Scope                                                                                  |
|--------|---------|----------------------------------------------------------------------------------------|
| 1      | GH-169  | Add `## Entities`, `## Norms`, `## Safeguards` to the three ticket-scope templates    |
| 2      | GH-170  | Build Norms/Safeguards autopopulator (path-aware rule matching, render-on-generation) |
| 3      | GH-171  | Create `Dev10x:spec-update` skill (logic-change flow)                                  |
| 4      | GH-172  | Create `Dev10x:spec-sync` skill (refactor flow)                                        |
| 5      | GH-173  | Wire spec-drift checks into `Dev10x:gh-pr-respond` + `Dev10x:git-groom`                |
| 6      | GH-174  | Add `structured-spec` play to `Dev10x:work-on` + suitability gate in Phase 1          |
| 7      | GH-175  | Document the SPDD-style pipeline in `references/skill-pipelines.md`                    |

## References

### External

- [Martin Fowler — Structured Prompt-Driven Development](https://www.martinfowler.com/articles/structured-prompt-driven/)
- `openspdd` reference CLI — wrapped tooling explicitly **out of scope** per GH-70 ("map concepts, not the tool")

### Internal

- `skills/scope/instructions.md` — base scoping workflow
- `skills/ticket-scope/instructions.md` — Linear-aware extension,
  including the three section templates
- `skills/adr/SKILL.md` — ADR format used here
- `skills/jtbd/SKILL.md` — Job Story drafting (Requirements layer)
- `references/skill-pipelines.md` — current shipping pipeline
- `.claude/rules/essentials.md`, `.claude/rules/INDEX.md` —
  source of truth for Norms autopopulation
