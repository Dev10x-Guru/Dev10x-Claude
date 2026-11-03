---
name: dev10x:adr
description: >
  Create Architecture Decision Records (ADRs) following project conventions.
  Extends the base scope skill with ADR-specific format, numbering, diagram
  generation, and decision documentation.
  TRIGGER when: documenting significant architectural decisions, design
  trade-offs, or technology choices that affect the codebase.
  DO NOT TRIGGER when: making code changes without architecture impact,
  or writing commit messages (use dev10x:git-commit).
user-invocable: true
invocation-name: dev10x:adr
persona: >
  Staff architect who writes for the engineer implementing the
  decision long after the discussion; names the alternatives it
  rejected and why each lost.
allowed-tools:
  - Bash(mkdir -p:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/diagram-sequence/scripts/render.sh:*)
  - Bash(ls:*)
  - Skill(dev10x:ticket-branch)
  - Skill(dev10x:git-commit)
  - Skill(dev10x:gh-pr-create)
  - Agent
  - WebFetch
  - Grep
  - Glob
  - Read
---

# ADR Create - Architecture Decision Record Skill

**Persona:** Staff architect who writes for the engineer implementing
the decision long after the discussion; names the alternatives it
rejected and why each lost.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create Architecture Decision Record", activeForm="Creating ADR")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

This skill creates Architecture Decision Records (ADRs) following
the project's established format. It extends the base `dev10x:scope`
skill with ADR-specific workflows.

**Use when:**
- Documenting significant architectural decisions
- Proposing new integration patterns
- Recording technology choices
- Documenting system boundaries and responsibilities

**Do NOT use when:**
- Simple bug fixes (no architectural impact)
- Minor refactoring within existing patterns
- Configuration changes

## Prerequisites

Before invoking this skill, gather:
1. **Problem context** - What situation needs a decision?
2. **External references** (optional) - Documentation, API docs
3. **Linear ticket** (optional) - Associated ticket for linking

## Workflow

### Phase 1: Discovery (Uses base scope skill)

Follow the base `dev10x:scope` skill for context gathering:

1. **Understand the problem space**
   - What are we trying to solve?
   - What constraints exist?

2. **Research external resources** (if any)
   - Fetch and analyze documentation
   - Extract key concepts and patterns

3. **Explore existing codebase**
   - Find related patterns
   - Identify reusable components
   - Note naming conventions

4. **Identify components**
   - What exists vs. what's needed
   - Dependencies between components

### Phase 2: ADR-Specific Design

#### 2.1 Determine ADR Number

```bash
ls docs/adr/*.md | grep -E '^docs/adr/[0-9]{4}-' | sort | tail -1
```

If last is 0009, next is 0010.

#### 2.2 Create ADR Structure

Use the template in `references/adr-template.md` for the full
structure. Key sections:

- **Context** — situation, current state, problems
- **Decision** — architecture, key flows, new components
- **Alternatives Considered** — pros/cons/verdict for each
- **Consequences** — what becomes easier, harder, risks
- **Implementation Plan** — phased steps with file paths
- **References** — external docs, internal links

Default status: **Accepted**. Use Proposed only when explicitly
requesting review before acceptance.

#### 2.3 Create Diagrams Directory

```bash
mkdir -p docs/adr/diagrams/{ADR_NUMBER}/
```

### Phase 3: Diagram Creation

Use PlantUML patterns from `references/plantuml-patterns.md`.

#### 3.1 Component Architecture Diagram

Shows system boundaries and component relationships.

#### 3.2 Sequence Diagrams

Shows flow of operations for key interactions.

#### 3.3 Generate PNG Files

Render each `.puml` with one call to the shared script — it writes
the PNG beside the source and runs PlantUML under the SANDBOX
security profile, so a diagram taken from a ticket or PR cannot pull
local files or environment variables into the image:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/diagram-sequence/scripts/render.sh docs/adr/diagrams/{ADR_NUMBER}/<name>.puml
```

A local `!include` is refused (`cannot include <path>`): inline the
content; only the jar's stdlib (`!include <C4/...>`) resolves. Fix and
re-run until it prints `rendered:`, then read the PNG. Details:
`${CLAUDE_PLUGIN_ROOT}/references/diagrams/rendering.md`.

### Phase 4: Apply Design Principles

**YAGNI (You Aren't Gonna Need It):**
- Don't design features that aren't needed yet
- Remove unused return values
- Prefer void methods over complex returns

**Follow Existing Patterns:**
- Find similar implementations in codebase
- Use same layering (Entry Point → Service → Client)
- Follow naming conventions

**Clean Architecture:**
- Keep external dependencies at edges
- Business logic independent of frameworks
- Clear component responsibilities

### Phase 5: User Review Loop

**Critical:** Present findings to user and incorporate corrections.

Common corrections include:
- Business context not visible in code
- Organizational preferences
- Future plans affecting design
- YAGNI simplifications

**Iterate until user approves the architecture.**

### Phase 6: Finalize and Commit

#### 6.1 Create Branch

Use `dev10x:ticket-branch` skill if a ticket exists, or
`dev10x:git-worktree` for isolated workspace.

#### 6.2 Commit ADR

Use the `dev10x:git-commit` skill to commit:
- Stage `docs/adr/` directory
- Gitmoji: 📝
- Title: outcome-focused (e.g., "Document payment routing
  architecture")

#### 6.3 Create PR

Use `dev10x:gh-pr-create` skill for PR creation.

## ADR Quality Checklist

Before finalizing, verify:

### Content
- [ ] Context clearly explains the problem
- [ ] Decision is explicit and actionable
- [ ] Alternatives genuinely considered
- [ ] Consequences are honest (both easier and harder)
- [ ] Risks have mitigations

### Architecture
- [ ] Follows existing codebase patterns
- [ ] YAGNI applied
- [ ] Clean Architecture respected
- [ ] Component responsibilities clear

### Diagrams
- [ ] Component architecture shows system boundaries
- [ ] Sequence diagrams show key flows
- [ ] PNGs generated and referenced in ADR

### Implementation
- [ ] Steps ordered logically
- [ ] File paths specified
- [ ] Pattern references included
- [ ] Phases make sense

### Review
- [ ] User feedback incorporated
- [ ] Business context accurate
- [ ] Ready for implementation

## Integration with Other Skills

```
dev10x:adr
├── Extends: dev10x:scope (base scoping workflow)
├── May use: dev10x:work-on (if ticket exists)
├── Uses: dev10x:gh-pr-create (for PR creation)
└── Uses: dev10x:git-commit (for commit formatting)
```

## References

### ADR Format
- [Michael Nygard's ADR article](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions)
- [adr-tools](https://github.com/npryce/adr-tools)

### Project ADR Location
- ADRs: `docs/adr/NNNN-title.md`
- Diagrams: `docs/adr/diagrams/NNNN/`

### PlantUML
- Generate: `${CLAUDE_PLUGIN_ROOT}/skills/diagram-sequence/scripts/render.sh docs/adr/diagrams/NNNN/<name>.puml`
- Themes: `!theme plain` for clean diagrams
