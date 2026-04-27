---
name: Dev10x:project-audit
invocation-name: Dev10x:project-audit
description: >
  Comprehensive project-level architecture audit. Catalogs design
  patterns from multiple sources, stress-tests domain models, maps
  JTBD from PR history against test coverage, and produces a
  prioritized improvement backlog.
  TRIGGER when: user requests architecture audit, project health
  check, pattern catalog mapping, or comprehensive quality review.
  DO NOT TRIGGER when: reviewing a single branch (use Dev10x:review),
  scoping a single ticket (use Dev10x:ticket-scope), or running a
  DDD workshop (use Dev10x:ddd-workshop).
user-invocable: true
allowed-tools:
  - Agent
  - AskUserQuestion
  - WebFetch
  - Grep
  - Glob
  - Read
  - Write(docs/memos/**)
  - Bash(gh pr list:*)
  - Bash(gh api repos/:*)
  - TaskCreate
  - TaskUpdate
  - Skill(Dev10x:project-scope)
  - Skill(Dev10x:adr)
  - Skill(Dev10x:ticket-create)
  - mcp__plugin_Dev10x_cli__detect_tracker
---

# Dev10x:project-audit — Comprehensive Architecture Audit

## Overview

Five-phase orchestration skill that audits a project's architecture,
design patterns, domain model health, and test coverage. Produces a
prioritized improvement backlog with milestones and blocking chains.

**Use when:**
- Inheriting a codebase and need a quality baseline
- Preparing for a major release or architecture evolution
- Running a periodic health check
- Mapping delivered value (JTBD) against test coverage

**Do NOT use for:**
- Single-branch code review → `Dev10x:review`
- Single-ticket scoping → `Dev10x:ticket-scope`
- DDD domain modeling → `Dev10x:ddd-workshop`
- Single-PR QA analysis → `Dev10x:qa-scope`

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each phase, immediately start the next.
Only pause at the Phase 2 selection gate and Phase 4 synthesis
review.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Phase 1: Detect project context", activeForm="Detecting context")`
2. `TaskCreate(subject="Phase 2: Select audit phases", activeForm="Selecting phases")`
3. `TaskCreate(subject="Phase 3: Execute audit phases", activeForm="Auditing")`
4. `TaskCreate(subject="Phase 4: Synthesize findings", activeForm="Synthesizing")`
5. `TaskCreate(subject="Phase 5: Create backlog", activeForm="Creating backlog")`

## Arguments

```
/Dev10x:project-audit                 # full audit (all phases)
/Dev10x:project-audit --phases B,C,E  # selected phases only
/Dev10x:project-audit --skip-backlog  # findings memo without tickets
/Dev10x:project-audit --memo-only     # memo without tickets or backlog
```

---

## Phase 1: Detect Project Context

Auto-detect project characteristics. Create subtasks per detection:

1. **Language & framework** — scan for `pyproject.toml`, `package.json`,
   `Cargo.toml`, `go.mod`, `pom.xml`. Identify Django, FastAPI, Rails,
   Next.js, SvelteKit, etc.
2. **Architecture style** — look for `src/` bounded contexts, Clean
   Architecture layers, service directories, DI containers.
3. **Module inventory** — list top-level modules/apps with line counts.
4. **Test infrastructure** — identify test runner, fixture patterns,
   coverage config. Map coverage by module.
5. **PR history** — fetch up to 200 recent closed/merged PRs:
   `gh pr list --state merged --limit 200 --json title,body,labels`
   Extract JTBD patterns from titles and bodies.
6. **Existing ADRs** — scan for `docs/adrs/`, `docs/decisions/`,
   `adr/` directories.
7. **Tracker** — detect issue tracker via
   `mcp__plugin_Dev10x_cli__detect_tracker`.

Store context as structured data for Phase 3 agent prompts.

---

## Phase 2: Select Audit Phases

**If `--phases` argument provided:** Skip the gate, use specified
phases.

**Otherwise:**

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call
spec: [ask-phase-selection.md](./tool-calls/ask-phase-selection.md)).

Present all 9 phases with descriptions. User selects which to run.

| Phase | Name | What it finds |
|-------|------|---------------|
| A | Pattern Catalog | Maps 50+ patterns from 3 catalogs to codebase |
| B | Domain Model Health | Anemic models, Tell Don't Ask violations |
| C | Value Object Discovery | Primitives that should be Value Objects |
| D | Archetype Stress Test | Software Archetypes structural alignment |
| E | Concurrency Audit | Missing locks, transactions, race conditions |
| F | Behavioral Pattern Fit | Strategy, CoR, Template Method opportunities |
| G | JTBD Coverage Matrix | Feature JTBD vs test coverage gaps |
| H | Cross-Cutting Consistency | Inconsistent patterns across modules |
| I | Cross-Context Queries | Multi-protocol resolvers, N+1 patterns, API type leaks |

---

## Phase 3: Execute Audit Phases (Parallel Agents)

Dispatch one `Explore` agent per selected phase. All agents run
concurrently in a single tool-call block. Agent dispatch template
and rules are in `references/agent-dispatch.md`.

Create one subtask per phase under the Phase 3 parent task.
Mark each completed as its agent returns.

Phase-specific instructions for each agent are in
`references/phase-prompts.md`. Detection heuristics are in
`references/detection-heuristics.md`.

Before dispatching, fetch pattern catalogs via `WebFetch`.
Fallback to hardcoded lists in `references/pattern-catalogs.md`.

1. **Fowler PoEAA** — `https://martinfowler.com/eaaCatalog/`
2. **Refactoring Guru** — `https://refactoring.guru/design-patterns/catalog`
3. **Software Archetypes** — `https://www.softwarearchetypes.com/`

---

## Phase 4: Synthesize Findings

After all agents return:

1. **Merge findings** — collect all structured finding blocks.
2. **Deduplicate** — same file:line appearing in multiple phases.
3. **Prioritize** — sort by Impact (HIGH first), then by Effort
   (S first within same impact).
4. **Group into milestones** — natural groupings:
   - Domain model improvements (B, C findings)
   - Pattern adoption (A, F findings)
   - Safety improvements (D, E findings)
   - Coverage gaps (G, H findings)
5. **Write findings memo** — create `docs/memos/architecture-audit-YYYY-MM-DD.md`
   with full findings, priority matrix, and milestone proposals.
6. **Draft ADR proposals** — for HIGH-impact findings that represent
   architectural decisions, propose ADRs via `Skill(Dev10x:adr)`.

**If `--memo-only`:** Stop here. Present memo and skip Phase 5.

### Synthesis Review Gate

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Present the findings summary and milestone groupings:

Options:
- Approve and create backlog (Recommended)
- Edit milestones — adjust groupings before ticket creation
- Stop here — keep memo, skip backlog creation

---

## Phase 5: Create Backlog

Delegate to `Skill(Dev10x:project-scope)` with the milestone
structure from Phase 4.

For each milestone:
1. Create a parent issue/epic with the milestone description
2. Create child issues for each finding within the milestone
3. Set blocking chains (safety findings block feature findings)
4. Label issues with audit phase (e.g., `audit:domain-health`)

**If `--skip-backlog`:** Skip this phase entirely.

Report final summary: milestones created, total issues, blocking
chains established.

---

## Important Notes

- Phase 3 agents use `Explore` type (read-only, no edits)
- Findings format in `references/finding-format.md` is strict
- Memo location defaults to `docs/memos/`
