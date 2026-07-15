---
name: Dev10x:work-on
description: >
  Start work on any input — ticket URL, PR link, Slack thread,
  Sentry issue, or free text. Classifies inputs, gathers context
  in parallel, builds a supervisor-approved task list, and executes
  adaptively with pause/resume support.
  TRIGGER when: user provides ticket URLs, PR links, Slack threads,
  Sentry issues, or free text to start structured work.
  DO NOT TRIGGER when: simple one-off tasks that don't need structured
  planning, or parallel fanout of independent items (use Dev10x:fanout).
user-invocable: true
invocation-name: Dev10x:work-on
allowed-tools:
  - mcp__plugin_Dev10x_cli__*
  - Read(.claude/Dev10x/playbooks/work-on.yaml)
  - Read(~/.config/Dev10x/playbooks/work-on.yaml)
  - Read(~/.claude/memory/Dev10x/playbooks/work-on.yaml)
  - Read(${CLAUDE_PLUGIN_ROOT}/skills/playbook/references/playbook.yaml)
  - Edit(.claude/Dev10x/**)
  - Skill(skill="Dev10x:verify-acc-dod")
  - mcp__plugin_Dev10x_cli__plan_sync_set_context
  - mcp__plugin_Dev10x_cli__plan_sync_json_summary
  - AskUserQuestion
---

# Dev10x:work-on — Adaptive Work Orchestrator

Turns any combination of inputs into a structured,
supervisor-approved work plan executed in four phases: parse,
gather, plan, execute.

## Instructions

The full orchestration contract — phase tasks, playbook
resolution, subagent dispatch, skill routing enforcement, and
completion gate — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. The `TaskCreate`, `TaskUpdate`, and
`AskUserQuestion` calls documented there are REQUIRED (blocking,
not advisory); do not substitute plain-text acknowledgements
for tool calls.
