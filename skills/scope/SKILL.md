---
name: dev10x:scope
invocation-name: dev10x:scope
description: >
  Base scoping skill for technical research and architecture design.
  Provides reusable scoping workflow for investigating codebases,
  designing solutions, and documenting decisions.
  TRIGGER when: performing technical research or architecture design
  without a specific tracker integration.
  DO NOT TRIGGER when: scoping a Linear ticket (use dev10x:ticket-scope),
  documenting an ADR (use dev10x:adr), or scoping a project (use
  dev10x:project-scope).
user-invocable: false
allowed-tools:
  - Agent
  - WebFetch
  - Grep
  - Glob
  - Read
  - Bash(java -jar:*)
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
---

# dev10x:scope — Base Technical Scoping

Foundational scoping skill providing reusable research and
architecture-design workflows. Not directly invocable — extended
by `dev10x:ticket-scope`, `dev10x:adr`, `dev10x:project-scope`,
`dev10x:project-audit`.

## Instructions

The full workflow — research phases, design passes, ADR
formatting, diagram rendering, decision documentation — lives in
[`instructions.md`](instructions.md).

When this skill is invoked (directly or via an extension skill),
Read `instructions.md` now and follow it end-to-end.
