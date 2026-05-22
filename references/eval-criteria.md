# Eval Criteria Guide

Eval criteria define measurable test scenarios and quality dimensions for skills.
This guide covers structure, assertion types, and best practices for skill authors.

## Overview

Each skill eval file contains:
1. **Skill metadata** — invocation name, dimensions
2. **Eval scenarios** — representative test cases with assertions
3. **Trigger guards** — when the skill should/should not activate

Evals are descriptive (JSON), enabling human code review and future test automation.

## File Structure

All evals live in `skills/<feature>/evals/evals.json`:

```json
{
  "skill_name": "Dev10x:example",
  "eval_dimensions": [
    {
      "id": "dimension-id",
      "name": "Dimension Name",
      "description": "What this tests"
    }
  ],
  "evals": [
    {
      "id": 1,
      "name": "scenario-name",
      "prompt": "/Dev10x:example <args>",
      "description": "High-level scenario",
      "setup": { /* env setup */ },
      "dimensions": ["dimension-ids"],
      "assertions": [ /* see types below */ ]
    }
  ],
  "trigger_evals": {
    "description": "When to trigger vs. not trigger",
    "should_trigger": [ /* queries that should */ ],
    "should_not_trigger": [ /* queries that should not */ ]
  }
}
```

## Assertion Check Types

### String-Based Checks

| Type | Use | Example |
|------|-----|---------|
| `output_contains` | Signal appears in skill output | `"signal": "Deploy successful"` |
| `output_not_contains` | Signal does NOT appear | Verify cleanup happened |
| `command_contains` | Command was executed | `"signals": ["gh pr create", "--draft"]` |
| `command_absent` | Command was NOT executed | Verify no destructive operations |
| `transcript_contains` | Signal in reasoning phase | Verify planning logic |

### Pattern-Based Checks

| Type | Use | Example |
|------|-----|---------|
| `output_matches_pattern` | Regex match | `"pattern": "^[🤖] [A-Z]"` (gitmoji format) |
| `output_not_starts_with` | Output doesn't begin with value | Verify not silent failure |
| `line_length` | Verify constraint (requires `max_chars`) | Enforce commit title ≤72 chars |

### Tool-Based Checks

| Type | Use | Example |
|------|-----|---------|
| `tool_called` | Tool was invoked | `"signals": ["Agent", "subagent_type"]` |
| `tool_called_count` | Count of tool calls | Signal format: `"="` or `">"`/`"<"` (e.g., `"=4"`) |
| `tool_not_called` | Tool was NOT invoked | Verify no unintended delegation |

### Behavioral Checks

| Type | Use |
|------|-----|
| `behavioral` | Observational check (no signals), requires transcript inspection |
| `output_contains_structure` | Output has headings/sections |
| `task_exists` | Task list contains matching task |

## Dimension Design

Dimensions are orthogonal quality axes (not sequential steps). Examples:

**Dev10x:work-on** (6 dimensions):
- `classify` — input type identification (URL, ID, free text)
- `gather` — parallel subagent context gathering
- `plan` — task list generation with mandatory elements
- `execute` — auto-advance + batched decisions (no checkpoints under adaptive friction)
- `task-structure` — 4 phase-level tasks + dependencies
- `workspace` — early workspace decision (main repo vs. worktree)

**Dev10x:git-commit** (5 dimensions):
- `format` — gitmoji + ticket + description pattern
- `jtbd` — outcome-focus verb enforcement
- `extraction` — ticket ID from branch name
- `safety` — protected branch guards
- `workflow` — interactive preview + approval

## Trigger Guards

Populate `trigger_evals` to prevent false positives:

```json
"trigger_evals": {
  "description": "When to trigger vs. not trigger",
  "should_trigger": [
    "I want to commit my changes with a formatted message",
    "git commit from branch feature/JIRA-123/my-work"
  ],
  "should_not_trigger": [
    "How do I undo the last commit?",
    "Show me the commit history"
  ]
}
```

Aim for **5–6 examples each** (should_trigger, should_not_trigger).

## Scenario Best Practices

1. **Concrete + Representative** — Use real-world prompts
   - ✅ `/Dev10x:work-on https://github.com/org/repo/issues/42`
   - ❌ `/Dev10x:work-on test`

2. **One dimension per scenario** — Scenarios focus on specific quality axis
   - Don't test all dimensions in one scenario
   - Spreads coverage across ~5–7 scenarios per skill

3. **Setup context** — Provide environment state
   ```json
   "setup": {
     "branch": "feature/PAY-310/fix-flaky-tests",
     "repo_state": "clean"
   }
   ```

4. **Observable signals** — Use verifiable transcript events
   - Skill output (console)
   - Commands executed (Bash, scripts)
   - Tools called (Agent, Bash, etc.)
   - NOT internal reasoning or unobservable state

5. **Assertion granularity** — 5–10 assertions per scenario
   - One assertion per observable signal
   - Use multiple assertions to triangulate correctness

## Quality Checklist

Before submitting eval PR:

- [ ] All eval scenarios target documented dimensions
- [ ] Trigger guards have 5+ `should_trigger` and 5+ `should_not_trigger` examples
- [ ] Each assertion uses a defined check type
- [ ] Signals are observable (output, commands, tool calls)
- [ ] Scenario setup reflects real-world conditions
- [ ] No hardcoded file paths (use patterns like `~/.claude/projects/**/*`)
- [ ] `skill_name` uses `Dev10x:` prefix
- [ ] File placed in `skills/<feature>/evals/evals.json`

## Evolution

As skills mature:
- Add new dimensions if gaps emerge
- Expand trigger guards with false positive cases
- Create integration evals when skills delegate to others

Monitor eval coverage across PRs. If a skill consistently behaves differently than evals expect, update the evals to reflect learned patterns.
