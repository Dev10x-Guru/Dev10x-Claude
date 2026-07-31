# Session Modes: Determination, Task Lists, and Scaffolding

Read this before creating tasks or choosing which workflow branch to
follow. SKILL.md keeps only the `REQUIRED: Create tasks before ANY
work` contract statement and the Discussion-Agent Model Tier gate
inline; the full per-mode task enumeration and the new-workshop
scaffold live here.

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

## Per-Mode Task Lists

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
