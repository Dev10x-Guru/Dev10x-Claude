---
name: dev10x:gh-pr-monitor
description: >
  Launch a background agent to monitor PR CI checks and review comments,
  automatically address issues with fixup commits, and notify team when
  ready. Use after creating a PR to automate the entire review cycle.
  TRIGGER when: PR has been created and needs CI/review monitoring.
  DO NOT TRIGGER when: PR does not exist yet (use dev10x:gh-pr-create
  first), or user wants to manually handle review comments.
user-invocable: true
invocation-name: dev10x:gh-pr-monitor
allowed-tools:
  - Agent
  - Skill(dev10x:gh-pr-respond)
  - Skill(dev10x:git-commit)
  - Skill(dev10x:git-groom)
  - Skill(dev10x:qa-scope)
  - Skill(dev10x:slack-review-request)
  - Skill(dev10x:ticket-jtbd)
  - Skill(dev10x:verify-acc-dod)
  - AskUserQuestion
  - mcp__plugin_dev10x_cli__pr_notify
  - mcp__plugin_dev10x_cli__detect_tracker
  - mcp__plugin_dev10x_cli__pr_detect
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-merge/scripts/:*)
  - mcp__plugin_dev10x_cli__ci_check_status
  - mcp__plugin_dev10x_cli__check_top_level_comments
  - mcp__plugin_dev10x_cli__bot_review_status
  - mcp__plugin_dev10x_cli__pr_wait
  - mcp__plugin_dev10x_cli__milestone_close
  - mcp__plugin_dev10x_cli__background_preamble
  - mcp__plugin_dev10x_cli__resolve_gate
  - Bash(gh:*)
  - Skill(dev10x:qa-scope)
  - Skill(dev10x:request-review)
  - Skill(dev10x:verify-acc-dod)
---

# PR Review Monitor (Background Agent)

Launch a background agent that monitors a PR through its full
lifecycle — CI checks, review comments, team notification — so
the user can keep working.

## Arguments

- PR URL or number (optional) — passed to `pr_detect`; empty
  detects the PR for the current branch.
- `--unattended` (GH-1911) — nobody is watching this run. No phase
  fires a notification widget: an `external_notify` gate that
  resolves to `ask` is treated as `skip`, and Phase 3 passes
  `--unattended` on to `dev10x:request-review`. Without the flag
  the run is still unattended when `resolve_gate`'s `run_mode.mode`
  says so — an `afk` overlay or a work-on plan step in progress
  (GH-1921, `references/review-readiness.md`). Strip the flag
  before handing the PR argument to `pr_detect`.

## Instructions

The full workflow — background dispatch, polling loop, fixup
handling, team notification, verification — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` and `AskUserQuestion` calls
documented there are REQUIRED.

`instructions.md` fits in one `Read` (GH-1922). It holds the
orchestration, the task list and a phase index; each phase body
lives in `references/phase-*.md` and is linked from that index.
Read a phase's file when the supervisor reaches the phase — Phase
3 (the review request and its `--unattended` pass-through) is in
`references/phase-3-notification.md`.

## Mandatory Invocation After PR Creation (GH-162)

Audit GH-162 caught a session where work-on task 4.9
"Monitor CI → delegate to `dev10x:gh-pr-monitor`" was in the
plan but never executed; the session ended immediately after
a single inline `gh pr view` status check (turn 279) and CI
completion was never confirmed.

**Hard rule:** After `dev10x:gh-pr-create` succeeds, the very
next action MUST be `Skill(dev10x:gh-pr-monitor)` — no
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
