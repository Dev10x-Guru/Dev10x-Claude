---
name: dev10x:skill-index
description: >
  Generate a family-grouped, adaptive-density skill index.
  Scans local skills and all installed plugins, groups by
  families.yaml, hides orchestration deps via hidden.yaml,
  and writes ~/.claude/SKILLS.md (≤45 lines, ≤300 chars/line).
  TRIGGER when: regenerating SKILLS.md after adding, removing, or
  renaming skills.
  DO NOT TRIGGER when: viewing the existing skill index, or editing
  individual skills.
user-invocable: true
invocation-name: dev10x:skill-index
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/skill-index/scripts/generate-all.sh:*)
  - mcp__plugin_dev10x_cli__generate_skill_index
  - Read(~/.claude/SKILLS.md)
  - Read(~/.claude/.skills-menu.txt)
---

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Generate skill index", activeForm="Generating index")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Instructions

Regenerate both skill index files by running the generator script:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/skill-index/scripts/generate-all.sh --force
```

Then display the generated files to the user:

```bash
cat ~/.claude/SKILLS.md
cat ~/.claude/.skills-menu.txt
```
