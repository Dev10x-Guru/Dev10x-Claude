---
name: dev10x:estimate
invocation-name: dev10x:estimate
description: >
  Estimate a ticket, a project, or an ad-hoc change the way the work
  actually ships: AI-agent implementation plus the human steps that
  still gate delivery — review, review wait, testing and docs — with
  effort and elapsed time reported separately.
  TRIGGER when: anyone asks how long something will take, what it
  would take to build X, how many points a ticket is, or when a
  release or milestone can land.
  DO NOT TRIGGER when: measuring time already spent (use a work
  report), or benchmarking code performance.
user-invocable: true
allowed-tools:
  - Read
  - Grep
  - Glob
  - mcp__plugin_dev10x_cli__issue_get
  - mcp__plugin_dev10x_cli__supervisor_review_status
  - mcp__claude_ai_Linear__get_issue
---

# dev10x:estimate — Agent-Built Work Estimation

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Estimate work", activeForm="Estimating work")`

Mark completed when the estimate is delivered:
`TaskUpdate(taskId, status="completed")`

## Overview

The method lives in one place:
[`references/estimation.md`](../../references/estimation.md). This
skill is the entry point that applies it — it adds no rules of its
own, so `dev10x:ticket-scope`, `dev10x:project-scope` and
`dev10x:work-on` produce the same numbers when they apply the same
file.

**Never fall back to a human-pace, one-engineer estimate.** That
default is the defect this skill exists to replace (GH-1495).

## Workflow

1. **Read the method.** `Read` `references/estimation.md` in full
   before producing any number — the scale, line items and roll-up
   rules are there, not here.
2. **Identify the unit.** A single ticket, a project or milestone
   (several tickets with a blocking chain), or an ad-hoc change
   described in prose.
3. **Gather just enough scope.** Fetch the ticket
   (`mcp__plugin_dev10x_cli__issue_get` or the Linear tool) when an ID
   is given, and `Grep` / `Glob` for the code it touches. Stop once the
   size and the human gates are clear — this is sizing, not scoping.
   For a full scoping pass use `dev10x:ticket-scope`.
4. **Resolve review wait from posture.** Call
   `mcp__plugin_dev10x_cli__supervisor_review_status()` for a repo
   the session can see. `none` in a solo repo means the wait is
   effectively zero; otherwise state the pickup time you assumed.
5. **Fill every line item** — agent implementation, human review,
   review wait, testing, documentation — with effort and elapsed.
   Write a zero rather than dropping a row.
6. **Roll up** (project-level only): sum effort; follow the critical
   path for elapsed; name the gate that dominates elapsed time.
7. **Deliver** in the Output Format of the reference, with the
   assumptions listed. When the size reaches 13 points, recommend a
   split instead of a number.
