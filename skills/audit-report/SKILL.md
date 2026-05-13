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

### Step 3: Fictionalize proprietary information (REQUIRED)

**Treat the source session as private by default.** The upstream
issue is a public artifact at `Dev10x-Guru/Dev10x-Claude` and MUST
NOT disclose any identifier from a non-public repository, project,
branch, ticket tracker, file path, person, or service that is not
part of the public Dev10x plugin.

Instead of redacting private identifiers with bracketed
placeholders (`<private-repo>`, `TICKET-NN`), **replace them with
similar-sounding fictional counterparts drawn from pop culture** —
movies, books, TV, cartoons, video games. The resulting issue
reads as a coherent story while leaking nothing. Real precedents:
issue #68 used `initech/initech-pos` + reviewer `skywalker`;
issue #98 used Tyrell Corp + Aperture Labs.

Apply the vibe-matching guide, consistency rule, and 6-step
algorithm in
[`references/privacy-scrub.md`](references/privacy-scrub.md) to
the verbatim findings text **before** assembling the issue body.

**REQUIRED: Call `AskUserQuestion`** when a finding is
fundamentally about a private codebase pattern that cannot be
retold through fictional stand-ins without losing the technical
point (do NOT use plain text). Options:

- Fictionalize aggressively and file (Recommended) — pick the
  closest pop-culture stand-in even at the cost of some
  specificity
- Skip this finding — exclude from upstream, keep in local notes

Never auto-include unfictionalized text. Re-read the assembled
body and verify every named entity is fictional (pop-culture
sourced, not a real company / person / product) before
continuing to Step 4.

### Step 4: Generate issue body

Build the issue body from the **fictionalized** findings:

```markdown
## Audit Findings

**Plugin version**: Dev10x {version}
**Session context**: {fictional-org}/{fictional-repo} / {fictional-branch}
**Audit date**: {date}

### Findings

| # | Phase | Classification | Skill | Description |
|---|-------|---------------|-------|-------------|
{fictionalized rows}

### Proposed Fixes

{fictionalized fixes, grouped by skill}

### Evidence

{fictionalized transcript excerpts — 2-3 lines per finding, no
real file paths, real handles, or real product names}
```

The "Session context" line uses fictional stand-ins (e.g.,
`initech/initech-pos / skywalker/CORE-401/death-star-3/...`) so
the report reads as a coherent narrative — the upstream
maintainer does not need the real repo or branch to act on a
Dev10x plugin finding.

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
  to a private codebase. Fictionalize repo names, owners,
  branches, tracker IDs, file paths, hostnames, and personal
  identifiers using pop-culture stand-ins (movies, books,
  cartoons, games) before assembling the issue body. Never use
  real company, product, or person names — even ones that *sound*
  fictional. Only the public Dev10x plugin context — skill names,
  plugin file paths, and `Dev10x-Guru/Dev10x-Claude` issue/PR
  numbers — is allowed verbatim. Re-verify every named entity is
  fictional before filing.
