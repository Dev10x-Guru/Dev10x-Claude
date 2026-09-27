---
name: dev10x:fanout
description: >
  Process multiple independent work items as a worktree-isolated
  swarm — each item runs the full dev10x:work-on lifecycle inside
  its own background Agent with isolation="worktree". Honors
  dependencies, minimizes conflicts, auto-advances by default.
  TRIGGER when: 2+ independent work items need parallel processing
  (PRs, issues, tickets).
  DO NOT TRIGGER when: single task or sequential dependency chain
  (use dev10x:work-on); already running as a swarm child (see
  recursive-fanout guard).
user-invocable: true
invocation-name: dev10x:fanout
allowed-tools:
  - AskUserQuestion
  - Skill(dev10x:friction-setup)
  - Skill(dev10x:gh-pr-create)
  - Skill(dev10x:gh-pr-merge)
  - Skill(dev10x:gh-pr-monitor)
  - Skill(dev10x:gh-pr-respond)
  - Skill(dev10x:git)
  - Skill(dev10x:git-branch-prune)
  - Skill(dev10x:git-groom)
  - Skill(dev10x:py-test)
  - Skill(dev10x:skill-audit)
  - Skill(dev10x:ticket-branch)
  - Skill(dev10x:work-on)
  - Skill(test)
  - Agent
  - Skill(skill="dev10x:work-on")
  - Skill(skill="dev10x:gh-pr-respond")
  - Skill(skill="dev10x:gh-pr-monitor")
  - Skill(skill="dev10x:git-groom")
  - Skill(skill="dev10x:git-commit")
  - Skill(skill="dev10x:gh-pr-create")
  - Skill(skill="dev10x:ticket-branch")
  - Skill(skill="dev10x:gh-pr-merge")
  - Skill(skill="dev10x:session-wrap-up")
  - Skill(skill="dev10x:skill-audit")
  - Skill(skill="dev10x:git-branch-prune")
  - Skill(skill="dev10x:friction-setup")
  - Edit(~/.claude/Dev10x/**)
  - Bash(uvx dev10x session set-friction:*)
  - Bash(dev10x session set-friction:*)
  - mcp__plugin_dev10x_cli__*
---

# dev10x:fanout — Parallel Work Stream Orchestrator

Close multiple open loops in parallel while honoring
dependencies and minimizing conflicts. Each item runs its full
pipeline — no collapsed shipping sequence.

## Instructions

The full workflow — 6-phase execution model, permission-aware
dispatch, parallel group management, completion gate — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` calls and the Strategy
`AskUserQuestion` gate documented there are REQUIRED.

**End-to-end read enforcement (GH-166, GH-1279): this file does
NOT fit in one `Read`.** The first call returns a truncated
`PARTIAL view` and stops around line 1209 of 1451. Keep issuing
`Read(offset=…)` until you reach the final line — the tail holds
the teardown decision tree and the Phase 5 comment-resolution
gate, and a truncated read drops both while looking complete.
If you did not see the last line, you have not read the contract.
