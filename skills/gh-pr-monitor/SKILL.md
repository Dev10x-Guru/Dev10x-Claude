---
name: Dev10x:gh-pr-monitor
description: >
  Launch a background agent to monitor PR CI checks and review comments,
  automatically address issues with fixup commits, and notify team when
  ready. Use after creating a PR to automate the entire review cycle.
  TRIGGER when: PR has been created and needs CI/review monitoring.
  DO NOT TRIGGER when: PR does not exist yet (use Dev10x:gh-pr-create
  first), or user wants to manually handle review comments.
user-invocable: true
invocation-name: Dev10x:gh-pr-monitor
allowed-tools:
  - Agent
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__pr_notify
  - mcp__plugin_Dev10x_cli__detect_tracker
  - mcp__plugin_Dev10x_cli__pr_detect
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-merge/scripts/:*)
  - mcp__plugin_Dev10x_cli__ci_check_status
  - mcp__plugin_Dev10x_cli__check_top_level_comments
  - mcp__plugin_Dev10x_cli__milestone_close
  - mcp__plugin_Dev10x_cli__background_preamble
  - mcp__plugin_Dev10x_cli__resolve_gate
  - Bash(gh:*)
  - Skill(Dev10x:qa-scope)
  - Skill(Dev10x:request-review)
  - Skill(Dev10x:verify-acc-dod)
---

# PR Review Monitor (Background Agent)

Launch a background agent that monitors a PR through its full
lifecycle — CI checks, review comments, team notification — so
the user can keep working.

## Instructions

The full workflow — background dispatch, polling loop, fixup
handling, team notification, verification — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` and `AskUserQuestion` calls
documented there are REQUIRED.

## Mandatory Invocation After PR Creation (GH-162)

Audit GH-162 caught a session where work-on task 4.9
"Monitor CI → delegate to `Dev10x:gh-pr-monitor`" was in the
plan but never executed; the session ended immediately after
a single inline `gh pr view` status check (turn 279) and CI
completion was never confirmed.

**Hard rule:** After `Dev10x:gh-pr-create` succeeds, the very
next action MUST be `Skill(Dev10x:gh-pr-monitor)` — no
exceptions. Orchestrators that mark the monitor task
`completed` without invoking the skill (e.g., via a one-off
`gh pr view` or inline polling) commit a compliance
violation. The skill's background-dispatch model is the
contract; substituting inline polling skips the fixup,
notification, and verification side effects.

**Notification gate resolution (ADR-0016, GH-757):** The Phase
2.7 and Phase 3 notification steps each call
`resolve_gate(gate="external_notify")` and branch on the
returned `effect` (`ask` / `auto-advance` / `skip`). The
resolver applies session policy — including the
solo-maintainer overlay — so this skill does NOT special-case
`active_modes` or `solo_maintainer` in prose. See
`instructions.md` Phase 2.7 and Phase 3 for the branch
pattern. The skill still runs Phases 1–2 (CI monitoring +
fixup handling) and Phase 4 (verification) regardless of the
notification gate's effect.
