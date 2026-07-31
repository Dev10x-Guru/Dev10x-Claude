---
name: Dev10x:skill-audit
description: >
  Audit a session's skill usage, compliance, and extract lessons learned.
  Default (lightweight): analyzes visible context inline and presents a
  disposition gate — no separate terminal needed for most audits.
  Forensic (--full or escalation): dispatches parallel subagents for deep
  transcript analysis — run from a separate terminal.
  TRIGGER when: session is complete and user wants usage review, or
  a skill didn't behave as expected.
  DO NOT TRIGGER when: mid-session during active work, or user is
  asking about a specific skill's documentation.
user-invocable: true
invocation-name: Dev10x:skill-audit
allowed-tools:
  - Agent
  - AskUserQuestion
  - Read(~/.claude/**)
  - Read(~/.claude/skills/**)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Read(/tmp/Dev10x/skill-audit/**)
  - Edit(~/.claude/**)
  - Edit(/tmp/Dev10x/skill-audit/**)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/skill-audit/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/bin/check-skill-eval-gaps.py:*)
  - mcp__plugin_Dev10x_cli__audit_extract_session
  - mcp__plugin_Dev10x_cli__audit_analyze_actions
  - mcp__plugin_Dev10x_cli__audit_analyze_permissions
  - mcp__plugin_Dev10x_cli__resolve_plugin_origin
  - Bash(ls -t ~/.claude/:*)
  - Bash(wc:*)
  - Bash(git config --list:*)
  - Bash(ls ~/.config/fish/functions/:*)
  - Bash(ls ~/.claude/tools/:*)
  - Bash(find ~/.claude/skills:*)
  - Skill(Dev10x:ticket-create)
  - Skill(Dev10x:audit-file)
---

# Skill Audit

Analyze a Claude Code session transcript for skill compliance,
missed invocations, user corrections, and process improvements
worth persisting into skill definitions.

## Strategies

**Lightweight (default):** Works from visible conversation
context. No transcript extraction, no subagent fan-out. Presents
inline findings and a structured disposition gate. Runs in the
current session — no separate terminal needed.

**Forensic (`--full` or escalation):** Full transcript extraction
and Wave 1/2 subagent fan-out. Use when the lightweight path
cannot answer, or when the supervisor explicitly requests deep
analysis. Run from a separate terminal.

## Instructions

The full workflow — strategy selection, task creation, session
resolution, wave orchestration, phase references, and reporting —
lives in [`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` calls, `AskUserQuestion`
gates, and `Agent` dispatches documented there are REQUIRED.

## Decision Gates

Each gate below blocks execution until the user responds.
**REQUIRED: Call `AskUserQuestion`** — do NOT use plain text.

1. Phase 0 Step 0c — lightweight disposition (file / escalate /
   discard). Call spec:
   [`tool-calls/ask-early-insight.md`](tool-calls/ask-early-insight.md)
2. Forensic Step 1.1 — confirm the auto-resolved session file.
   Call spec:
   [`tool-calls/ask-session-confirm.md`](tool-calls/ask-session-confirm.md)
3. Phase 7 sub-step B — whether to report upstream
4. Phase 7 sub-step B2 — **where** to report: confirm the issue
   tracker(s) detected from each offending skill's owning plugin
   (GH-816). Call spec:
   [`tool-calls/ask-target-tracker.md`](tool-calls/ask-target-tracker.md)

Gates 1, 2, and 4 are ALWAYS_ASK — they fire at every friction
level, including `adaptive`.
