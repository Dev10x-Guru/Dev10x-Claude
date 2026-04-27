---
name: Dev10x:audit-report
description: >
  File skill-audit findings as a GitHub issue at the Dev10x plugin repo.
  Invoked by skill-audit Phase 7 when the user opts in.
  TRIGGER when: skill-audit Phase 7 completes and user opts to file upstream.
  DO NOT TRIGGER when: no audit findings exist, or user wants to review
  findings before filing.
user-invocable: true
invocation-name: Dev10x:audit-report
allowed-tools:
  - Read(/tmp/Dev10x/skill-audit/**)
  - Write(/tmp/Dev10x/skill-audit/**)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Skill(Dev10x:ticket-create)
  - Bash(ls ~/.claude/plugins/cache/:*)
  - Bash(gh issue create:*)
---

# Audit Report — File Findings Upstream

Generate a structured GitHub issue from skill-audit findings
and file it at `Dev10x-Guru/dev10x-claude`.

## When to Use

- Delegated by `Dev10x:skill-audit` Phase 7 after the user
  approves upstream reporting
- Can also be invoked standalone with a findings file

## Arguments

One required argument: path to a findings markdown file
produced by `Dev10x:skill-audit`. The file contains:

```markdown
## Session Context

- **Repo**: {repo-name}
- **Branch**: {branch-name}
- **Date**: {audit-date}

## Upstream Findings

| # | Phase | Classification | Skill | Description |
|---|-------|---------------|-------|-------------|
| 1 | ... | ... | ... | ... |

## Proposed Fixes

{Grouped by skill}
```

If no argument is provided, check for the most recent file in
`/tmp/Dev10x/skill-audit/` matching `findings*.md`.

## Workflow

### Step 1: Read findings

Read the findings file passed as argument. Validate it contains
at least one finding row in the table.

If empty or missing, inform the user and exit.

### Step 2: Determine plugin version

```bash
ls ~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude/
```

Use the version directory name (e.g., `0.19.0.dev0`). If the
cache directory is not found, use `unknown`.

### Step 3: Generate issue body

Build the issue body from the findings file:

```markdown
## Audit Findings

**Plugin version**: Dev10x {version}
**Session context**: {repo} / {branch}
**Audit date**: {date}

### Findings

| # | Phase | Classification | Skill | Description |
|---|-------|---------------|-------|-------------|
{rows from findings file}

### Proposed Fixes

{fixes from findings file, grouped by skill}

### Evidence

{transcript excerpts from findings file, if present —
2-3 lines of context per finding, not full transcript}
```

### Step 4: Derive issue title

Use the primary skill name (most findings) as the title anchor:

- Single skill: `skill-audit findings: Dev10x:{skill}`
- Multiple skills: `skill-audit findings: Dev10x:{skill} (+N)`

### Step 5: Write body to temp file

```bash
/tmp/Dev10x/bin/mktmp.sh skill-audit upstream-issue .md
```

Write the assembled body to that file using the Write tool.

### Step 6: File the issue

Delegate to `Dev10x:ticket-create` — never use raw `gh issue create`.
Write the title as the first line of the temp file (followed by a
blank line and the body) to avoid permission friction from special
characters in the args string:

```
Skill(skill="Dev10x:ticket-create",
  args="--repo Dev10x-Guru/dev10x-claude --body-file {temp-file-path} --label enhancement")
```

The ticket-create skill reads the first line as the title when
no `--title` flag is provided.

### Step 7: Report result

Display the created issue URL. If filing fails, show the error
and the temp file path so the user can file manually.

## Important Rules

- **Always use `--body-file`**: Never pass the body inline via
  `--body` — markdown tables break shell quoting.
- **Plugin skills only**: This skill files issues about Dev10x
  plugin skills. User-local findings should never appear in the
  issue body.
- **No transcript dumps**: Evidence sections include 2-3 lines
  of context per finding, not raw transcript blocks.
- **One issue per audit**: Batch all findings into a single
  issue per audit session to avoid issue spam.
