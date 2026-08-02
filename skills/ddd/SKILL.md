---
name: Dev10x:ddd
invocation-name: Dev10x:ddd
description: >
  Run or continue a DDD Event Storming workshop to explore, model, and
  stress-test domain architecture.
  TRIGGER when: user mentions DDD, domain modeling, event storming, bounded
  contexts, domain events, aggregates, "workshop", "domain session", "stress
  test the architecture", "apply archetype", "scope the domain", or asks
  domain exploration questions like "add tax support" or "what breaks if we
  add goods pricing". Always use before ticket-scope when the feature area
  is new or crosses bounded context boundaries.
  DO NOT TRIGGER when: implementing code within a well-understood domain, or
  scoping a ticket in a known bounded context (use Dev10x:ticket-scope).
user-invocable: true
allowed-tools:
  - TaskCreate
  - TaskUpdate
  - AskUserQuestion
  - Agent
  - Glob
  - Grep
  - Read
  - Edit(docs/**)
  - Bash(mkdir -p docs:*)
---

# DDD Event Storming Workshop

Guide users through structured domain exploration using DDD Event
Storming, Software Archetypes, and architecture stress testing.

## When to Use

**Trigger on:** starting or continuing a domain modeling session,
exploring a new feature area, stress-testing the architecture,
applying/recognizing a Software Archetype, scoping a feature that
crosses bounded context boundaries, or resolving an implementation
contradiction.

**Do NOT use for:** scoping a single well-defined ticket (use
`ticket-scope`), writing an ADR for an already-decided topic (use
`write-adr`), or pure implementation tasks with no domain questions.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next — no checkpoints under adaptive friction.
Only pause when batching questions per the process rules.

**REQUIRED: Create tasks before ANY work.** After determining the
session type (see `references/session-modes.md` § Determine Session
Type), execute the `TaskCreate` calls for the applicable mode —
**Continue / Stress-Test / Archetype** or **New workshop**. Both
share the same 6-step shape (load-or-scaffold, explore, stress-test,
decide, produce artifacts, quality checklist); full per-mode call
lists live in `references/session-modes.md` § Per-Mode Task Lists.
Set sequential dependencies; mark each step `in_progress` on start
and `completed` when done. Quality checklist is the final gate.

## Determine Session Type

Before starting, read `references/session-modes.md` § Determine
Session Type for the full mode-trigger table (new workshop /
continue / stress test / archetype) and the solo-vs-multi-participant
default.

### Discussion-Agent Model Tier (solo mode)

Discussion agents (persona panel + devil's advocate) perform
judgment work — their entire output IS the discussion, so the
cost-tiering rationale for fetch/prep agents does not apply (GH-789).

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) ONCE
per session before the first AI-cast dispatch, batched with the
persona-selection confirmation (`references/solo-facilitation.md`
§ Selecting personas — never as a standalone interruption). Options:
**Frontier (Recommended)** — omit `model:` so agents inherit the
session default; **Sonnet** — budget middle ground; **Haiku** —
quick smoke-run only (warn: naive output, no interaction-level
thinking).

Persist the choice for the whole session and use it for BOTH
persona rounds (blind generation + stress-test round) AND the
devil's advocate. See `references/solo-facilitation.md`
§ Cost & Cadence Defaults.

---

## Step 1: Load Context (Continue/Stress-Test modes)

Read these files **in this order** before proceeding: `model.md`
(current domain model), `decisions.md` (append-only prior
decisions), `calculator.md` (calculation formulas, if present),
`stress-tests.md` (validated architectural seams), `glossary.md`
(ubiquitous language), `epics.md` (tickets and priorities), and the
latest file in `workshops/` (previous session). Then read
implementation state: the project's domain source directory
(locate via CLAUDE.md or glob for the model types named in
`model.md`), and `CLAUDE.md` (project conventions).

**Summarize** what you understand in 3-5 sentences before proceeding.

For **new workshops**, skip to `references/session-modes.md` §
New Workshop: Scaffolding, then proceed to Step 2.

---

## Step 2: Process Rules

Read `references/process-rules.md` for the full set.

- **Minimize interruptions** — go as long as possible without
  asking questions. Make reasonable assumptions, note alternatives,
  store unresolved choices. Only stop when the choice is genuinely
  arbitrary or high-stakes. When you DO need input, **batch ALL
  questions into a single structured decision menu** — never one
  question at a time.
- **Protect accumulated decisions** — never re-derive or silently
  override a decision in `decisions.md`. If new info contradicts a
  prior decision, propose a NEW decision that explicitly supersedes
  it (state which, why, what changes downstream). Reference
  decisions by ID: `[D-NNN]`.
- **Genericize proprietary data** — use reference materials
  (spreadsheets, specs) as behavioral models. Replace proprietary
  specifics with generic examples. The domain model must never leak
  client IP.

---

## Step 3: Exploration

Read `references/exploration-methodology.md` for DDD techniques.

### Event Storming Flow

In solo mode, run layers 1–4 with the persona panel's blind
generation protocol (`references/solo-facilitation.md`): elicit the
human's events first, dispatch personas in parallel, present the
overlap analysis as one batched menu.

1. **Identify domain events** — what happens in the system? (orange)
2. **Identify commands** — what triggers each event? (blue)
3. **Identify actors** — who issues each command? (yellow)
4. **Identify policies** — what rules fire after events? (lilac)
5. **Identify aggregates** — what data clusters together?
6. **Identify bounded contexts** — where are the seams?
7. **Identify value objects** — what are the typed quantities?

### Cross-Reference Checks

At each exploration layer, cross-check four references:

- `../../references/domain/archetypes-catalog.md` — at every stage,
  check whether this problem matches a known Software Archetype
  (21-signal recognition table). **Applying an archetype is NOT
  premature abstraction** — it's recognizing a solved problem; the
  archetype provides vocabulary and structure, the domain provides
  the specific rules.
- `../../references/domain/design-patterns.md` — tactical/strategic pattern
  selection (aggregate rules, context mapping ladder, when NOT to
  CQRS/ES) and workshop-method guidance
- `../../references/domain/anti-patterns.md` — detection signals per workshop
  stage; the devil's advocate agent uses this catalog
- `../../references/domain/standards-and-references.md` — before inventing a
  vocabulary, check whether an industry standard settled it
  (Money → ISO 4217, recurrence → RFC 5545 RRULE, supply-chain
  events → EPCIS, banking contexts → BIAN)

### Integration & Topology Probe (guided)

Once bounded contexts are named (layer 6) and someone asks
"separate services?", run
`../../references/domain/integration-patterns.md`: decide modular
monolith vs split *per context*, check every boundary against the
leak table ("could the other side change its internals without us
noticing?"), and fill one contract line **per context-map edge**
(style, artifact, pattern). Record topology and per-edge choices as
`[D-NNN]` decisions.

### Authorization Probe (guided)

When actors multiply, commands become identity-dependent, or
"role"/"owner"/"visibility" enter the language, run the guided
authorization section in `../../references/domain/authz-patterns.md`:
classify each guarded command's grant sentence into **RBAC / ABAC /
ReBAC / Capability** (bearer invitation for accountless actors —
ask forwardability, scope, expiry, redemption-identity), place the
five policy-architecture boxes (PEP, PDP, PIP, PRP, PAP) on the
context map, and record the model + engine choice as a `[D-NNN]`
decision. Rule: invariants ≠ permissions — permission checks live at
the PEP, never inside aggregates.

### Design Philosophy

These principles govern all proposals made during exploration — see
[`references/exploration-methodology.md`](references/exploration-methodology.md)
§ Design Philosophy for the full set ("don't make me think",
configuration vs. estimation, foundation-ready hooks, deferred
server dependencies).

---

## Step 4: Stress Testing

Before committing to any model change, validate it. Read
`references/stress-test-protocol.md` for the full protocol.

In solo mode, dispatch the devil's advocate before decision
capture on structural changes, and collect one "what if" scenario
per persona (`references/solo-facilitation.md`).

### Quick stress-test checklist

1. **Trace through every pipeline stage** — ZERO changes / additive
   / breaking, per stage.
2. **Check the stable core** — verify `stress-tests.md` "Stable
   Core" components remain stable.
3. **Identify seams** — hook missing? Assess cost now vs. deferred.
4. **Check against prior decisions** — conflicts with `decisions.md`?
5. **Endgame scale test** — airport scale? (10-year project, 5000
   items, 50 departments, mixed product types, multi-currency,
   hierarchical policy)

---

## Step 5: Decision Capture

Every choice gets recorded. Read
`references/session-deliverables.md` for the full format.

### Decision format

See `references/session-deliverables.md` § Decision Log Entries for
the full `D-NNN` template. To supersede: add a new decision with
`supersedes: D-NNN`, update the old entry's status to `Superseded by
D-NNN`.

---

## Step 6: Produce Artifacts

Read `references/session-deliverables.md` for complete format and
`references/document-structure.md` for file responsibilities.

**Always produce:** new entries in `decisions.md` (every choice,
even "decided not to do X") and a workshop record in
`workshops/NNN-topic.md` (narrative, decisions, model changes, open
questions).

**When applicable:** updated `model.md`, `calculator.md`,
`epics.md`, `glossary.md`; a new `stress-tests.md` scenario; new
Claude CLI prompts in `docs/prompts/` when a feature area is fully
scoped. New tickets divide into **configuration** and **estimation**
tickets — each needs a JTBD Job Story, scope, acceptance criteria,
dependencies (see `epics.md`).

**Optional presentation:** for a long workshop record, or a decision
whose alternatives are easier to weigh side by side, consider also
rendering it as an HTML artifact — see
[`../../references/html-artifact-reporting.md`](../../references/html-artifact-reporting.md).
Optional, never a gate: the markdown deliverables above remain the
durable record and the quality checklist passes without an artifact.

---

## Reference Files

Read on demand — SKILL.md is the workflow; references hold the depth.

| File | Read when |
|---|---|
| `references/session-modes.md` | Determining session mode; creating tasks; scaffolding a new workshop |
| `references/process-rules.md` | Starting any session |
| `references/solo-facilitation.md` | Starting any session (solo default: personas, devil's advocate, [ASSUMPTION] guardrail) |
| `references/exploration-methodology.md` | Doing event storming or domain modeling |
| `../../references/domain/archetypes-catalog.md` | Recognizing or applying a Software Archetype |
| `../../references/domain/design-patterns.md` | Selecting tactical/strategic patterns; context mapping; workshop methods |
| `../../references/domain/anti-patterns.md` | Aggregate/context design reviews; devil's advocate dispatch; stress testing |
| `../../references/domain/standards-and-references.md` | Naming a vocabulary an industry standard may have settled |
| `../../references/domain/authz-patterns.md` | Actors/permissions surface: RBAC/ABAC/ReBAC decision + PEP/PDP/PIP/PRP/PAP placement |
| `../../references/domain/integration-patterns.md` | Contexts named, deployment/interface questions arise: modular monolith vs split, leak prevention, contract design |
| `references/stress-test-protocol.md` | Validating a model change or extension |
| `references/session-deliverables.md` | Producing artifacts at end of session |
| `references/document-structure.md` | Scaffolding docs/ for a new project |
| `../../references/html-artifact-reporting.md` | Deciding whether a long or comparison-heavy report is worth rendering as an HTML artifact (optional) |
| `../../references/domain/pricing-pipeline.md` | Working on pricing, rates, or cost calculation (worked archetype example) |
| `../../references/domain/bibliography.md` | Sourcing citations; pre-workshop facilitator ramp reading |

---

## Quality Checklist

Before ending a session, verify:

- [ ] All decisions recorded in `decisions.md` with IDs
- [ ] No prior decisions silently overridden (only explicitly superseded)
- [ ] Model.md reflects current state (not historical state)
- [ ] New terms added to glossary.md
- [ ] Stress test run if structural change was made
- [ ] Stable core validated against `stress-tests.md`
- [ ] Workshop record created in `workshops/NNN-topic.md`
- [ ] Proprietary data genericized in all outputs
- [ ] Seams identified: zero-cost hooks for future extensions
- [ ] Solo mode: no `[ASSUMPTION]` tags remain in model.md,
      decisions.md, or glossary.md
