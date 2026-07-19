---
name: Dev10x:foreman
description: >
  Unattended overnight delivery of a milestone/bundle queue — a
  two-tier harness (watchdog main session + cheap foreman overseer +
  work-on crew) that pre-flights permissions while the supervisor is
  still present, loops the queue, defers questionable scope to the
  end, survives quota-block rollovers, and self-audits its friction
  at dawn. Guided/strict friction levels — never YOLO auto-mode.
  TRIGGER when: the supervisor is leaving (AFK / overnight / "ship
  these milestones while I sleep") with 1+ milestones or issue
  bundles queued for autonomous delivery.
  DO NOT TRIGGER when: single attended bundle (use Dev10x:work-on),
  parallel independent items while attended (use Dev10x:fanout), or
  only the gate policy is wanted (use Dev10x:afk).
user-invocable: true
invocation-name: Dev10x:foreman
allowed-tools:
  - AskUserQuestion
  - Agent
  - Bash(dev10x foreman:*)
  - Skill(Dev10x:afk)
  - Skill(Dev10x:work-on)
  - Skill(Dev10x:fanout)
  - Skill(Dev10x:diag-friction)
  - Skill(Dev10x:skill-audit-queue)
  - Skill(Dev10x:session-wrap-up)
  - mcp__plugin_Dev10x_cli__issue_list
  - mcp__plugin_Dev10x_cli__issue_get
  - mcp__plugin_Dev10x_cli__issue_comment
  - mcp__plugin_Dev10x_cli__issue_create
  - mcp__plugin_Dev10x_cli__pr_get
  - mcp__plugin_Dev10x_cli__ci_check_status
  - mcp__plugin_Dev10x_cli__milestone_close
  - mcp__plugin_Dev10x_cli__background_preamble
  - mcp__plugin_Dev10x_cli__resolve_gate
  - mcp__plugin_Dev10x_cli__mktmp
---

# Dev10x:foreman — Overnight Milestone Delivery Harness

**Announce:** "Using Dev10x:foreman to pre-flight and run the
unattended delivery of [queue] while you're away."

The supervisor leaves the site; the foreman runs the crew; the
watchdog only restarts the foreman. In the morning the supervisor
reads the shift log — merged PRs, closed milestones, every decision
recorded, deferred scope commented on its issues.

## Instructions

The full workflow — Phase 0 pre-flight (the one-time permission
window), the two-tier night loop, stall/quota/base-movement
recovery, and the dawn self-audit — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and follow it
end-to-end. The Phase 0 `AskUserQuestion` gates (queue plan + model
mapping, friction level) and the pre-flight enumeration are
REQUIRED — they are what makes the night survivable.
