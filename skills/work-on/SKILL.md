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
  - Skill(Dev10x:friction-setup)
  - Skill(Dev10x:gh-context)
  - Skill(Dev10x:gh-pr-create)
  - Skill(Dev10x:gh-pr-merge)
  - Skill(Dev10x:gh-pr-monitor)
  - Skill(Dev10x:gh-pr-request-review)
  - Skill(Dev10x:gh-pr-respond)
  - Skill(Dev10x:git)
  - Skill(Dev10x:git-commit)
  - Skill(Dev10x:git-groom)
  - Skill(Dev10x:session-config-seed)
  - Skill(Dev10x:skill-create)
  - Skill(Dev10x:ticket-branch)
  - Skill(Dev10x:verify-acc-dod)
  - Skill(test)
  - Read(.claude/Dev10x/playbooks/work-on.yaml)
  - Read(~/.config/Dev10x/playbooks/work-on.yaml)
  - Read(~/.claude/memory/Dev10x/playbooks/work-on.yaml)
  - Read(${CLAUDE_PLUGIN_ROOT}/skills/playbook/references/playbook.yaml)
  - Edit(.claude/Dev10x/**)
  - Skill(skill="Dev10x:verify-acc-dod")
  - Skill(skill="Dev10x:friction-setup")
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

**End-to-end read enforcement (GH-166, GH-1279): this file does
NOT fit in one `Read`.** At ~2600 lines it is roughly twice the
token cap a single call returns, so the first `Read` comes back
truncated — `PARTIAL view … showing lines 1-1141 of 2627` — and an
agent that stops there is working from under half the contract
while believing it read the whole thing.

Keep issuing `Read(offset=…)` until you have reached the final
line. Do NOT substitute `Grep` or a single `Read(limit=…)` for the
missing pages: the guardrails are scattered, not sectioned. The
tail is where the Plan Completion Gate, the pre-gate checklist,
the merge-gated completion rule and the skill-routing table live —
a truncated read silently drops all four, which is exactly the
session GH-1279 documents.

If you did not see the last line of the file, you have not read
the contract.
