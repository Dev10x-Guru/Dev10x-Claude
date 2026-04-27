---
name: Dev10x:context-audit
description: >
  Audit context window utilization — CLAUDE.md files, rules, agent
  specs, references, and memories. Reports budget compliance, flags
  oversized files, and suggests pruning actions.
  TRIGGER when: user wants to optimize context usage, after adding
  many rules or memories, or when sessions feel sluggish from
  context bloat.
  DO NOT TRIGGER when: auditing memory content quality (use
  Dev10x:memory-maintenance instead).
user-invocable: true
invocation-name: Dev10x:context-audit
allowed-tools:
  - Read
  - Glob
  - Grep
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - Edit
  - Bash(pytest:*)
---

# Dev10x:context-audit — Context Window Optimizer

## Overview

Every file loaded into Claude's context window consumes capacity.
This skill audits all context sources against documented budgets,
identifies bloat, and suggests specific pruning actions.

Complements `Dev10x:memory-maintenance` (which audits memory
content quality) by covering the structural layer: file sizes,
budget compliance, and cross-file redundancy.

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Scan context sources", activeForm="Scanning")`
2. `TaskCreate(subject="Check budget compliance", activeForm="Checking budgets")`
3. `TaskCreate(subject="Detect redundancy", activeForm="Detecting redundancy")`
4. `TaskCreate(subject="Present findings and suggestions", activeForm="Presenting")`

Set sequential dependencies.

## Phase 1: Scan Context Sources

Discover all files that contribute to the context window.
Scan both the plugin directory and user-space locations.

### 1.1 Plugin Context (always loaded)

| Category | Location | Budget |
|----------|----------|--------|
| CLAUDE.md (project) | `<repo>/CLAUDE.md` | 100 lines |
| Rules | `<repo>/.claude/rules/*.md` | 200 lines each |
| Agent specs (internal) | `<repo>/.claude/agents/*.md` | 50 lines each |
| Agent specs (plugin) | `<repo>/agents/*.md` | 200 lines each |
| References | `<repo>/references/*.md` | 200 lines each |

### 1.2 User-Space Context

| Category | Location | Budget |
|----------|----------|--------|
| CLAUDE.md (global) | `~/.claude/CLAUDE.md` | No strict budget |
| SKILLS.md | `~/.claude/SKILLS.md` | 45 lines |
| MEMORY.md (global) | `~/.claude/memory/MEMORY.md` | 200 lines |
| Dev10x global config | `~/.claude/memory/Dev10x/**` | No per-file budget |

### 1.3 Collect Metrics

For each discovered file, record:
- **Path** (relative to repo or home)
- **Line count** (`wc -l`)
- **Category** (from tables above)
- **Budget** (from INDEX.md or table above)
- **Usage %** (line count / budget * 100)

## Phase 2: Check Budget Compliance

Compare each file against its budget. Classify:

| Usage | Status | Action |
|-------|--------|--------|
| ≤ 60% | OK | No action needed |
| 61-79% | WATCH | Monitor — approaching limit |
| 80-99% | WARNING | Plan a split (per INDEX.md) |
| ≥ 100% | OVER | Must split or prune |

### 2.1 Aggregate Metrics

Calculate totals per category:
- Total files scanned
- Total lines across all files
- Files at WARNING or OVER status
- Category with highest utilization

### 2.2 Budget Override Detection

Check for documented budget overrides in INDEX.md:

```
Grep for "Budget Overrides" section in .claude/rules/INDEX.md
```

Files with documented overrides get their override budget
instead of the default. Flag overridden files as INFO (not
WARNING) when they exceed the default but stay within the
override.

## Phase 3: Detect Redundancy

Scan for common redundancy patterns across context files:

### 3.1 Duplicate Content

Check for content that appears in multiple files:
- Same rule stated in both CLAUDE.md and a rules file
- Same convention in both a rule and a reference doc
- Memory entries that duplicate CLAUDE.md instructions

Use targeted grep for common patterns:
- Git conventions (branch naming, commit format)
- Testing patterns (pytest, coverage)
- Tool preferences (ruff, black, mypy)

### 3.2 Stale References

Check for references to files or paths that no longer exist:
- Rules referencing deleted agent specs
- INDEX.md entries pointing to missing references
- Memory files referencing renamed skills

### 3.3 Always-Loaded vs On-Demand

Identify files in `.claude/rules/` that could be moved to
`references/` (loaded on-demand by skills instead of every
session). Criteria:
- File is only relevant to one specific skill
- File exceeds 100 lines (high context cost)
- File has a clear skill owner (from INDEX.md routing)

## Phase 4: Present Findings and Suggestions

### 4.1 Budget Report

Present a table sorted by usage (highest first):

```
## Context Budget Report

| File | Lines | Budget | Usage | Status |
|------|-------|--------|-------|--------|
| .claude/rules/INDEX.md | 173 | 200 | 87% | WARNING |
| references/task-orchestration.md | 367 | 200 | 184% | OVER* |
| .claude/agents/reviewer-skill.md | 48 | 50 | 96% | WARNING |
| ... | ... | ... | ... | ... |

* Has documented budget override (cohesion justification)

### Summary
- 45 files scanned, 3,200 total lines
- 2 files OVER budget (1 with override)
- 3 files at WARNING level
- Estimated context: ~12% of window at session start
```

### 4.2 Redundancy Findings

List each redundancy found with:
- What is duplicated
- Where it appears (file:line for each occurrence)
- Suggested action (remove from X, keep in Y)

### 4.3 Pruning Suggestions

For each OVER or WARNING file, suggest specific actions:

| Suggestion Type | Example |
|----------------|---------|
| Split | "Split INDEX.md routing table into a separate file" |
| Move to reference | "Move X from rules/ to references/" |
| Remove duplicate | "Remove git convention from CLAUDE.md (already in rules)" |
| Consolidate | "Merge agent specs A and B (80% overlap)" |
| Prune stale | "Remove memory entry X (references deleted file)" |

### 4.4 Decision Gate

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Apply safe fixes (Recommended) — Remove stale refs, fix broken links
- Review each fix — Walk through suggestions one by one
- Report only — No changes, just the audit report
- Delegate to memory-maintenance — Hand off memory-specific findings

### 4.5 Apply Fixes (if approved)

For each approved fix:
1. Read the target file
2. Apply the edit (remove duplicate, update reference, etc.)
3. Verify the file is still valid after edit
4. Report what was changed

Never modify files without explicit user approval from the
decision gate above.
