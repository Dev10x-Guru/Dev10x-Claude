# Domain Documentation Structure

## Directory Layout

```
docs/
├── adr/                           # Architecture Decision Records
│   ├── TEMPLATE.md
│   └── NNN-slug.md
│
├── domain/                        # Domain knowledge
│   ├── README.md                  # Index and guide
│   ├── model.md                   # Current-state domain model
│   ├── calculator.md              # Calculator specification
│   ├── decisions.md               # Decision log (append-only)
│   ├── glossary.md                # Ubiquitous language
│   ├── stress-tests.md            # Architecture stress tests
│   ├── epics.md                   # Epics and tickets
│   └── workshops/                 # Session records
│       ├── TEMPLATE.md
│       └── NNN-topic.md
│
├── plans/                         # Implementation plans (per-epic)
│
└── prompts/                       # Reusable Claude CLI prompts
    ├── README.md
    └── *.md
```

## File Responsibilities

| File | Job | Mutability |
|---|---|---|
| `model.md` | **What the domain IS now.** Types, pipeline, aggregates, bounded contexts. No history. | Mutable (updated in place; git = history) |
| `calculator.md` | **How calculations work.** Formulas, pipeline stages, golden test values. Optional — only for domains with computation (pricing, scheduling, scoring). | Mutable |
| `decisions.md` | **Why we chose what we chose.** Every decision with ID, rationale, alternatives. | **Append-only.** Decisions never deleted, only superseded. |
| `glossary.md` | **What terms mean.** Domain term → definition → code mapping. | Mutable (terms added/refined) |
| `stress-tests.md` | **What we validated.** Scenarios, scorecards, stable core. | **Append-only.** New scenarios added, old ones preserved. |
| `epics.md` | **What to build.** Tickets with JTBD stories, scope, dependencies. | Mutable (tickets refined; completed marked `[DONE]`) |
| `workshops/NNN-*.md` | **What happened.** Historical record of each session. | **Immutable.** Written once, never edited after session ends. |

## Cross-Reference Conventions

- Decisions: `[D-NNN]` — e.g., `[D-014]`
- Glossary terms: `[G:term]` — e.g., `[G:PricingPolicy]`
- ADRs: `ADR-NNN` — e.g., `ADR-002`
- Tickets: `PERT-NN` — e.g., `PERT-20a`
- Stress test scenarios: `ST-N` — e.g., `ST-2`

## For Claude CLI: What to Read When

| Task | Read first | Then |
|---|---|---|
| Implement a ticket | model.md → calculator.md → epics.md | Relevant ADR |
| Scope a new ticket | model.md → decisions.md → epics.md | stress-tests.md if pricing |
| Write an ADR | decisions.md → model.md | adr/TEMPLATE.md |
| Continue a workshop | workshops/latest → decisions.md → model.md | stress-tests.md |
| Stress-test extension | model.md → calculator.md → stress-tests.md | decisions.md |

## Scaffolding Templates

### model.md (initial)

```markdown
# Domain Model: [Project Name]

> **Status:** Initial — Workshop 001
> **Archetypes:** (to be identified)

## Bounded Contexts

(to be discovered during event storming)

## Aggregates

(to be identified)

## Value Objects

(to be defined)
```

### decisions.md (initial)

```markdown
# Decision Log

> **Append-only.** Decisions are never deleted.
> To change a decision, add a new entry with `supersedes: D-NNN`.

(No decisions yet — first workshop will populate this.)
```

### calculator.md (initial)

```markdown
# Calculator Specification

> Pure functions. No framework dependencies.
> Each stage independently testable.

## Pipeline Stages

(to be defined during domain modeling)

## Golden Tests

(to be defined when formulas are established)
```

### glossary.md (initial)

```markdown
# Glossary — Ubiquitous Language

> Term → Definition → Code mapping. Alphabetical.

| Term | Definition | Code type / function |
|---|---|---|
| (to be populated during workshops) | | |
```

### stress-tests.md (initial)

```markdown
# Architecture Stress Tests

> Append-only. Each scenario validates the pipeline.

## Stable Core

(to be established after first archetype application)
```

### epics.md (initial)

```markdown
# Epics & Tickets

> Updated as tickets are refined. Completed = `[DONE]`.

## Implementation Priority

(to be determined)
```

### workshops/TEMPLATE.md

```markdown
# Workshop NNN: [Topic]

- **Date:** YYYY-MM-DD
- **Participants:** [names]
- **Brief:** [what question were we answering?]

## Key Findings
## Decisions Made
## Model Changes
## Open Questions
## Artifacts Produced
```
