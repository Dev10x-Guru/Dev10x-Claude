---
name: Dev10x:onboarding
description: >
  Guided discovery of Dev10x capabilities for new users. Interactive
  tour through skill families, git setup, PR pipeline, session
  management, and customization — adapted to experience level.
  TRIGGER when: user is new to Dev10x, asks what it can do, or
  wants a walkthrough of available capabilities.
  DO NOT TRIGGER when: user already knows what skill to use, or
  is asking about a specific feature (use that skill directly).
user-invocable: true
invocation-name: Dev10x:onboarding
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - Skill
  - mcp__plugin_Dev10x_cli__supervisor_review_status
  - mcp__plugin_Dev10x_cli__pin_supervisor_review
---

# Dev10x:onboarding — Guided Discovery

Interactive walkthrough introducing Dev10x in under 10 minutes.
Detects existing configuration and skips already-done steps.

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Detect user context", activeForm="Detecting context")`
2. `TaskCreate(subject="Guided tour", activeForm="Walking through capabilities")`
3. `TaskCreate(subject="Setup assistance", activeForm="Setting up")`

## Execution

Read and follow the tour guide:

```
Read(${CLAUDE_PLUGIN_ROOT}/skills/onboarding/references/tour-guide.md)
```

Execute each phase in order. Skip phases/sections based on
configuration detection results. Use `AskUserQuestion` at
every decision gate marked REQUIRED in the guide.
