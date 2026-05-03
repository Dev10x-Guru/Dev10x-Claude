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
  - AskUserQuestion
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

### Step 3: Scrub proprietary information (REQUIRED)

**Treat the source session as private by default.** The upstream
issue is a public artifact at `Dev10x-Guru/Dev10x-Claude` and MUST
NOT disclose any identifier from a non-public repository, project,
branch, ticket tracker, file path, person, or service that is not
part of the public Dev10x plugin.

Apply the replacement table, allow-list, and 5-step algorithm in
[`references/privacy-scrub.md`](references/privacy-scrub.md) to
the verbatim findings text **before** assembling the issue body.

**REQUIRED: Call `AskUserQuestion`** when a finding cannot be
reported without a private identifier (do NOT use plain text).
Options:

- Scrub aggressively and file (Recommended) — abstract the
  identifier even at the cost of specificity
- Skip this finding — exclude from upstream, keep in local notes

Never auto-include unscrubbed text. Re-read the assembled body
and verify no disallowed identifier remains before continuing
to Step 4.

### Step 4: Generate issue body

Build the issue body from the **scrubbed** findings:

```markdown
## Audit Findings

**Plugin version**: Dev10x {version}
**Session context**: <private-project> / <private-branch>
**Audit date**: {date}

### Findings

| # | Phase | Classification | Skill | Description |
|---|-------|---------------|-------|-------------|
{scrubbed rows}

### Proposed Fixes

{scrubbed fixes, grouped by skill}

### Evidence

{scrubbed transcript excerpts — 2-3 lines per finding, no
private file paths or identifiers}
```

The "Session context" line is intentionally generic — the
upstream maintainer does not need the original repo or branch
to act on a Dev10x plugin finding.

### Step 5: Derive issue title

Use the primary skill name (most findings) as the title anchor:

- Single skill: `skill-audit findings: Dev10x:{skill}`
- Multiple skills: `skill-audit findings: Dev10x:{skill} (+N)`

### Step 6: Write body to temp file

```bash
/tmp/Dev10x/bin/mktmp.sh skill-audit upstream-issue .md
```

Write the assembled body to that file using the Write tool.

### Step 7: File the issue

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

### Step 8: Report result

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
- **Privacy by default (Step 3)**: The source session may belong
  to a private codebase. Scrub repo names, owners, branches,
  tracker IDs, file paths, hostnames, and personal identifiers
  before assembling the issue body. Only the public Dev10x
  plugin context — skill names, plugin file paths, and
  `Dev10x-Guru/Dev10x-Claude` issue/PR numbers — is allowed
  verbatim. Re-verify the body is clean before filing.
