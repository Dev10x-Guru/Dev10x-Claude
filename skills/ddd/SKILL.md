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

**Trigger on:**
- Starting a new domain modeling session
- Continuing or refining an existing domain model
- Exploring a new feature area or extension
- Stress-testing the architecture against a future scenario
- Applying or recognizing Software Archetypes in the model
- Scoping a feature that crosses bounded context boundaries
- Resolving a contradiction found during implementation

**Do NOT use for:**
- Scoping a single well-defined ticket (use `ticket-scope` instead)
- Writing an ADR for an already-decided topic (use `write-adr` prompt)
- Pure implementation tasks with no domain questions

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next — no checkpoints under adaptive friction.
Only pause when batching questions per the process rules.

**REQUIRED: Create tasks before ANY work.** After determining
the session type, execute `TaskCreate` calls for the applicable
steps. The task set varies by mode:

**Continue / Stress-Test / Archetype mode:**
1. `TaskCreate(subject="Load context", activeForm="Loading domain context")`
2. `TaskCreate(subject="Exploration", activeForm="Exploring domain")`
3. `TaskCreate(subject="Stress testing", activeForm="Stress testing model")`
4. `TaskCreate(subject="Decision capture", activeForm="Capturing decisions")`
5. `TaskCreate(subject="Produce artifacts", activeForm="Producing artifacts")`
6. `TaskCreate(subject="Quality checklist", activeForm="Verifying quality")`

**New workshop mode:**
1. `TaskCreate(subject="Scaffold docs structure", activeForm="Scaffolding docs")`
2. `TaskCreate(subject="Exploration", activeForm="Exploring domain")`
3. `TaskCreate(subject="Stress testing", activeForm="Stress testing model")`
4. `TaskCreate(subject="Decision capture", activeForm="Capturing decisions")`
5. `TaskCreate(subject="Produce artifacts", activeForm="Producing artifacts")`
6. `TaskCreate(subject="Quality checklist", activeForm="Verifying quality")`

Set sequential dependencies. Mark each step `in_progress` when
starting and `completed` when done. The quality checklist task
serves as the final verification gate.

## Determine Session Type

Before starting, determine which mode applies:

| Mode | Trigger | Read before starting |
|---|---|---|
| **New workshop** | No `docs/domain/` exists yet | `references/document-structure.md` |
| **Continue workshop** | `docs/domain/model.md` exists | All existing domain docs (Step 1) |
| **Stress test** | "What if we add X?" / "Does Y break?" | `references/stress-test-protocol.md` |
| **Archetype application** | "This feels bloated" / "Apply archetype" | `../../references/domain/archetypes-catalog.md` |

**Participation default: solo.** Assume ONE human (domain expert +
decision-maker) facilitated by this skill with an AI cast — persona
panel for blind event generation, devil's advocate for structural
challenges. Read `references/solo-facilitation.md` at session start;
it defines the role-substitution map and the `[ASSUMPTION]`
guardrail. Multi-participant rooms are the exception: skip the AI
cast and facilitate the humans instead.

---

## Step 1: Load Context (Continue/Stress-Test modes)

Read these files **in this order** before proceeding:

1. `docs/domain/model.md` — current domain model
2. `docs/domain/decisions.md` — all prior decisions (append-only)
3. `docs/domain/calculator.md` — calculation formulas (if present)
4. `docs/domain/stress-tests.md` — validated architectural seams
5. `docs/domain/glossary.md` — ubiquitous language
6. `docs/domain/epics.md` — tickets and priorities
7. Latest file in `docs/domain/workshops/` — previous session

Then read implementation state:
8. The project's domain source directory (locate via CLAUDE.md or
   glob for the model types named in `model.md`), if any
9. `CLAUDE.md` — project conventions

**Summarize** what you understand in 3-5 sentences before proceeding.

For **new workshops**, skip to Step 2 and read
`references/document-structure.md` to scaffold the docs directory.

---

## Step 2: Process Rules

Read `references/process-rules.md` for the full set. Summary:

### Minimize interruptions

**Go as long as possible without asking questions.** Make reasonable
assumptions, note alternatives, store unresolved choices. Only stop
when the choice is genuinely arbitrary or high-stakes.

When you DO need input, **batch ALL questions into a single
structured decision menu** with options. Never one question at a
time.

### Protect accumulated decisions

**Never re-derive or silently override decisions from decisions.md.**
If new info contradicts a prior decision, propose a NEW decision
that explicitly supersedes it — state which, why, and what changes
downstream. Reference decisions by ID: `[D-NNN]`.

### Genericize proprietary data

Use reference materials (spreadsheets, specs) as behavioral models.
Replace proprietary specifics with generic examples. The domain
model must never leak client IP.

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

### Software Archetypes Recognition

Read `../../references/domain/archetypes-catalog.md` for the full pattern table.

At every stage, check: **does this problem match a known
archetype?** Run the 21-signal recognition table in
`../../references/domain/archetypes-catalog.md` — raw numbers with implied
units, flat config structs, party-shaped entities, time-bound
happenings, and bloated mixed-semantics entities all have named
decompositions there.

**Applying an archetype is NOT premature abstraction.** It's
recognizing that this problem has been solved before. The archetype
provides the vocabulary and structure; the domain provides the
specific rules. See `../../references/domain/archetypes-catalog.md` for the full
recognition table (21 signals), source landscape, and composition
guidance.

### Patterns, Anti-Patterns, and Standards

At each exploration layer, cross-check three references:

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
noticing?"), and fill one contract line per context-map edge
(style, artifact, pattern). Record topology and per-edge choices
as `[D-NNN]` decisions.

### Authorization Probe (guided)

When actors multiply, commands become identity-dependent, or
"role"/"owner"/"visibility" enter the language, run the guided
authorization section in `../../references/domain/authz-patterns.md`: classify
each guarded command's grant sentence into RBAC / ABAC / ReBAC /
Capability (bearer invitation for accountless actors — ask the
forwardability, scope, expiry, and redemption-identity probes),
place the five policy-architecture boxes (PEP, PDP, PIP, PRP,
PAP) on the context map, and record the model + engine choice as
a `[D-NNN]` decision. Rule of engagement: invariants ≠
permissions — permission checks live at the PEP, never inside
aggregates.

### Design Philosophy

These principles govern all proposals:

**"Don't make me think" (Krug)** — Prefer implicit automatic
behavior (auto-grouping on child add) over manual workflows. But
never auto-delete or auto-restructure — creation can be magic,
destruction requires intent.

**Configuration vs. Estimation** — Keep pricing configuration
cleanly separated from the estimation workspace. Users change
rules without touching estimates, and vice versa.

**Foundation-ready, not prematurely built** — Bake hooks into the
foundation (like i18n) so future capabilities are data extensions,
not refactors. **Rule of thumb:** nullable field or open union now
at zero runtime cost vs. data migration later → do it now.
Actual code/abstractions not yet used → defer.

**Plan but defer server dependencies** — Features requiring servers
(short URLs, cloud accounts) are scoped and designed but not built
until the client-side foundation is solid.

---

## Step 4: Stress Testing

Before committing to any model change, validate it. Read
`references/stress-test-protocol.md` for the full protocol.

In solo mode, dispatch the devil's advocate before decision
capture on structural changes, and collect one "what if" scenario
per persona (`references/solo-facilitation.md`).

### Quick stress-test checklist

1. **Trace through every pipeline stage** — for each stage, state:
   ZERO changes / additive / breaking.
2. **Check the stable core** — verify components in
   `stress-tests.md` "Stable Core" section remain stable.
3. **Identify seams** — if the extension needs a hook that doesn't
   exist, assess: cost now vs. cost if deferred.
4. **Check against prior decisions** — conflicts with `decisions.md`?
5. **Endgame scale test** — does this work at airport scale?
   (10-year project, 5000 items, 50 departments, mixed product
   types, multi-currency, hierarchical policy)

---

## Step 5: Decision Capture

Every choice gets recorded. Read
`references/session-deliverables.md` for the full format.

### Decision format

```markdown
## D-NNN: [Short title]

- **Date:** YYYY-MM-DD
- **Status:** Active | Superseded by D-MMM
- **Workshop:** NNN

**Decision:** [What was chosen]

**Alternatives considered:**
1. [Option A] — [why not]
2. [Option B] — [why not]

**Rationale:** [Why this choice]
```

To supersede: add new decision with `supersedes: D-NNN`, update
old entry's status to `Superseded by D-MMM`.

---

## Step 6: Produce Artifacts

Read `references/session-deliverables.md` for complete format and
`references/document-structure.md` for file responsibilities.

### Always produce

1. **New entries in `decisions.md`** — every choice, even "we
   decided not to do X"
2. **Workshop record** in `workshops/NNN-topic.md` — narrative,
   decisions list, model changes, open questions

### When applicable

3. Updated `model.md` (if types/pipeline/aggregates changed)
4. Updated `calculator.md` (if formulas/golden tests changed)
5. Updated `epics.md` (if tickets added/refined/completed)
6. New scenario in `stress-tests.md` (if stress test was run)
7. Updated `glossary.md` (if new terms introduced)
8. New Claude CLI prompts in `docs/prompts/` (if feature area
   is fully scoped and ready for implementation)

### Ticket format

Divide features into **configuration tickets** and **estimation
tickets**. Each ticket needs: JTBD Job Story, scope, acceptance
criteria, dependencies. See `epics.md` for established format.

---

## New Workshop: Scaffolding

When no `docs/domain/` exists, create the full structure. Read
`references/document-structure.md` for the complete specification.

```bash
mkdir -p docs/domain/workshops docs/prompts
```

Create these files from the templates in
`references/document-structure.md`:
- `docs/domain/README.md` — documentation architecture index
- `docs/domain/model.md` — domain model (initially empty scaffold)
- `docs/domain/decisions.md` — decision log (empty, with format guide)
- `docs/domain/calculator.md` — calculator spec (empty scaffold)
- `docs/domain/glossary.md` — ubiquitous language (empty table)
- `docs/domain/stress-tests.md` — stress tests (empty, with format)
- `docs/domain/epics.md` — epics and tickets (empty scaffold)
- `docs/domain/workshops/TEMPLATE.md` — workshop record template

Then proceed with exploration (Step 3).

---

## Reference Files

Read these on demand — SKILL.md contains the workflow; references
contain the depth.

| File | Read when |
|---|---|
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
