---
name: Dev10x:ticket-scope
description: >
  Scope Linear tickets with technical research and architecture design.
  Extends the base scope skill with Linear ticket integration, story
  point estimation, and acceptance criteria formatting.
  TRIGGER when: preparing to implement a Linear ticket — scoping
  technical approach, estimating story points, or writing acceptance
  criteria.
  DO NOT TRIGGER when: scoping non-Linear tickets, multi-ticket
  projects (use Dev10x:project-scope), or new domain areas (use
  Dev10x:ddd first).
user-invocable: true
invocation-name: Dev10x:ticket-scope
allowed-tools:
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__list_issues
  - mcp__claude_ai_Linear__list_comments
  - mcp__claude_ai_Linear__save_comment
  - Skill(Dev10x:jtbd)
  - Agent
  - WebFetch
  - Grep
  - Glob
  - Read
  - Bash(mkdir -p:*)
  - AskUserQuestion
---

# Ticket Scope — Linear Ticket Scoping Skill

Create comprehensive technical scoping documents for Linear
tickets. Extends the base `Dev10x:scope` skill with Linear-
specific workflows (ticket fetch, comment back, story point
estimation, acceptance criteria).

## Instructions

The full workflow — ticket fetch, context gathering, research
loop, story point sizing, AC generation, comment writeback —
lives in [`instructions.md`](instructions.md).

**REQUIRED before ANY other tool call:** Read
[`instructions.md`](instructions.md) end-to-end. The
orchestration contract (TaskCreate calls, phase ordering,
AskUserQuestion gates, mandatory delegations like
`Skill(Dev10x:jtbd)` and template selection) lives there —
not in this SKILL.md. Skipping the read causes downstream
phase bypasses (GH-26, GH-27, GH-28).

**Self-check after the read:** Confirm you can name the
six TaskCreate subjects, the Phase 4b skill delegation,
and the Phase 5.1 templates before fetching the ticket.
If you cannot, re-read the file. Do NOT proceed to
`mcp__plugin_Dev10x_cli__issue_get` (or any other tool)
until the read is complete.
