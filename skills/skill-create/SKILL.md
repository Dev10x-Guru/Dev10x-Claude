---
name: dev10x:skill-create
description: >
  Use when creating or improving a local skill and hitting friction — bash
  commands keep prompting for approval, the skill doesn't appear in MOTD,
  or it's unclear which frontmatter fields wire up invocability — so you
  get the Dev10x-specific setup right without hunting through existing
  skills for examples.
  TRIGGER when: creating a new skill, fixing skill registration, or
  scaffolding skill directory structure.
  DO NOT TRIGGER when: editing skill content without structural issues,
  or writing non-skill code.
user-invocable: true
invocation-name: dev10x:skill-create
allowed-tools:
  - AskUserQuestion
  - Bash(mkdir -p:*)
  - Bash(chmod:*)
  - Bash(rg:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/skill-create/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/skill-index/scripts/:*)
  - mcp__plugin_dev10x_cli__generate_skill_index
---

# Dev10x Skill Create

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create or improve skill", activeForm="Working on skill")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

**Announce:** "Using dev10x:skill-create to [create/improve] the `<name>` skill."

**Foundation:** Read `superpowers:writing-skills` first for TDD methodology,
CSO principles, and quality standards. This skill covers only the local
Dev10x conventions that sit on top of that foundation.

## Directory Layout

```
~/.claude/skills/
  <namespace>:<skill-name>/
    SKILL.md            # required
    scripts/            # executable helpers (optional)
    references/         # markdown reference docs (optional)
```

Active namespaces: `my:`, `dev10x:`, `ticket:`, `pr:`, `commit:`

## Frontmatter Template

```yaml
---
name: dev10x:my-skill-name
invocation-name: dev10x:my-skill-name
description: Use when [situation trigger] so [what the user gains or stops suffering]
user-invocable: true          # include for user-invocable skills
allowed-tools:                # pre-approve bash commands (removes prompts)
  - Bash(git commit:*)
  - Bash(~/.claude/skills/<name>/scripts/:*)
---
```

| Field | When to use |
|---|---|
| `name` | Canonical identifier; MUST use `dev10x:` prefix |
| `invocation-name` | Required on every skill; matches `name:` by default, or shorter alias |
| `user-invocable: true` | Skill appears in MOTD and is callable via Skill tool |
| `allowed-tools` | Pre-approve bash commands Claude needs; use `:*` for any args |

## Writing for User Gains (JTBD-influenced)

Descriptions, step rationale, and mistake consequences should communicate
**what changes for the user** — not what the skill covers or what steps do.

**Description:** situation + gain, not a feature list.

```
❌ Covers namespace conventions, user-invocable frontmatter, and MOTD registration.
✅ Use when bash commands keep prompting for approval or the skill won't appear
   in MOTD — so you get the wiring right without hunting existing skills.
```

**Step rationale:** what breaks without this step, not just what the step does.

```
❌ After creating or modifying any skill, regenerate the SKILLS.md index.
✅ Skills don't appear in session context until indexed. Regenerate so the
   new skill is discoverable at the next session start.
```

**Mistake consequence:** what the user can no longer do — not the technical cause.

```
❌ Forgot user-invocable: true → Skill won't appear in MOTD or be invocable.
✅ Forgot user-invocable: true → Skill exists but nobody can call it — silent failure.
```

## Announce Pattern

Every invocable skill MUST open with an announce line so Claude signals
which skill is running:

```markdown
**Announce:** "Using <skill-name> to [purpose matching the task]."
```

## Workflow

### 1. Scaffold

**Automated scaffold** (recommended):

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Script-based — Skill with executable scripts in scripts/
- Orchestration — SKILL.md-only workflow executed by Claude
- Reference-based — Orchestration with references/ docs

Then run the scaffold:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/skill-create/scripts/scaffold.sh <skill-name> <pattern>
```

This generates SKILL.md with correct frontmatter, evals/evals.json skeleton,
and pattern-specific directories (scripts/ or references/).

**Manual scaffold** (for edge cases):

```bash
mkdir -p ~/.claude/skills/<namespace>-<skill-name>
```

Then create `SKILL.md` following the frontmatter template above.

### 2. Write

Follow `superpowers:writing-skills` RED-GREEN-REFACTOR:

- **RED** — document what Claude does wrong without the skill
- **GREEN** — write minimal skill addressing those specific failures
- **REFACTOR** — close loopholes found during testing

### 3. Validate Structure

```bash
${CLAUDE_PLUGIN_ROOT}/skills/skill-index/scripts/generate-all.sh --force
rg -n "<namespace>-<skill-name>" ~/.claude/SKILLS.md ~/.claude/.skills-menu.txt
```

This validates frontmatter parsing and confirms the new skill is indexable.

### 4. Register in MOTD

Skills don't appear in session context until indexed. Regenerate so the
new skill is discoverable at the next session start (run this if you skipped
step 3 or made additional edits):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/skill-index/scripts/generate-motd.sh --force
```

## Patterns from Existing Skills

| Skill | Patterns to study |
|---|---|
| `dev10x:git-worktree` | Step-numbered workflow, `allowed-tools`, templates |
| `dev10x:ticket-create` | Prerequisites check, integration section |
| `dev10x:skill-index` | Minimal skill that fully delegates to a script |
| `commit` | Multi-step workflow with explicit validation gates |

## Calling Other Skills

Use the **Skill tool** or a `REQUIRED: Use <skill-name>` instruction line.
Never `@`-force-load another skill file — it consumes context immediately.

```markdown
## Prerequisites
**REQUIRED:** Invoke `dev10x:ticket-branch` before this workflow begins.
```

## Script Conventions

All scripts in `scripts/` must be executable so they can be invoked directly
and match the `Bash(~/.claude/skills/<name>/scripts/:*)` allow rule pattern.

### Making Scripts Executable

After creating any script in `scripts/`:

```bash
chmod +x ~/.claude/skills/<namespace>:<skill-name>/scripts/<script>
```

Or for all scripts in a skill at once:

```bash
chmod +x ~/.claude/skills/<namespace>:<skill-name>/scripts/*
```

### Shebang Selection

| Script type | Shebang | Invoke as |
|---|---|---|
| Python (any) | `#!/usr/bin/env -S uv run --script` + PEP 723 block | `~/.claude/skills/.../script.py` |
| Shell | `#!/usr/bin/env bash` or `#!/bin/bash` | `~/.claude/skills/.../script.sh` |

**PEP 723 block** (for uv scripts with dependencies):
```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "slack_sdk"]
# ///
```

### Invocation in SKILL.md

Call scripts directly — never prefix with `python3` or `bash`:

```bash
# ✅ Direct call — matches Bash(~/.claude/skills:*) allow rule
~/.claude/skills/<name>/scripts/my-script.py --arg value

# ❌ Prefixed — command starts with python3, not ~/.claude/skills
python3 ~/.claude/skills/<name>/scripts/my-script.py --arg value
```

### Why Direct Invocation Matters

The `allowed-tools` entry `Bash(~/.claude/skills/<name>/scripts/:*)` only
pre-approves commands whose prefix is `~/.claude/skills/...`. If the script
is invoked with `python3` or `bash` prefix, the prefix becomes `python3` or
`bash`, the allow rule doesn't match, and Claude prompts for approval on
every invocation.

## Common Mistakes

| Mistake | Consequence |
|---|---|
| Description lists features covered | Claude can't tell when to load it — skill never gets used |
| No `Announce:` line | User can't tell which skill is running when something goes wrong |
| Forgot `user-invocable: true` | Skill exists but nobody can call it — silent, invisible failure |
| MOTD not refreshed after creation | Skill missing from session context until next regeneration |
| `allowed-tools` without `:*` suffix | Every bash command in the workflow triggers an approval prompt |
| Script not marked executable | Direct invocation fails; `python3`/`bash` prefix breaks allow rule matching |
| `python3 ~/.claude/skills/...` in SKILL.md | Allow rule `Bash(~/.claude/skills:*)` doesn't match; prompts on every run |
