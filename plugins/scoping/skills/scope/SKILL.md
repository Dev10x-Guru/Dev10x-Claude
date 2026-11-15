---
name: dev10x-scoping:scope
invocation-name: dev10x-scoping:scope
description: >
  Base scoping skill for technical research and architecture design.
  Provides reusable scoping workflow for investigating codebases,
  designing solutions, and documenting decisions.
  TRIGGER when: performing technical research or architecture design
  without a specific tracker integration.
  DO NOT TRIGGER when: scoping a Linear ticket (use dev10x-scoping:ticket-scope),
  documenting an ADR (use dev10x-scoping:adr), or scoping a project (use
  dev10x-scoping:project-scope).
user-invocable: false
allowed-tools:
  - Agent
  - WebFetch
  - Grep
  - Glob
  - Read
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/diagram-sequence/scripts/render.sh:*)
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
---

# dev10x-scoping:scope — Base Technical Scoping

Foundational scoping skill providing reusable research and
architecture-design workflows. Not directly invocable — extended
by `dev10x-scoping:ticket-scope`, `dev10x-scoping:adr`, `dev10x-scoping:project-scope`,
`dev10x-scoping:project-audit`.

## Instructions

The full workflow — research phases, design passes, ADR
formatting, diagram rendering, decision documentation — lives in
[`instructions.md`](instructions.md).

When this skill is invoked (directly or via an extension skill),
Read `instructions.md` now and follow it end-to-end.
