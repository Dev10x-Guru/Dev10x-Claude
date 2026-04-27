---
name: Dev10x:gh-pr-doctor
description: >
  Use when merged PRs may have unresolved review threads
  accumulating as silent tech debt — so unaddressed feedback
  gets surfaced, grouped by theme, and tracked as issues.

  TRIGGER when: reviewing merged PRs for accumulated tech debt,
  or post-merge as part of maintenance workflow

  DO NOT TRIGGER when: reviewing active draft PRs, or as part of
  automated PR review (not designed for real-time feedback)
user-invocable: true
invocation-name: Dev10x:gh-pr-doctor
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-doctor/scripts/:*)
  - mcp__plugin_Dev10x_cli__unresolved_threads
  - AskUserQuestion
  - Bash(gh issue create:*)
---

# Dev10x:gh-pr-doctor

**Announce:** "Using Dev10x:gh-pr-doctor to audit merged PRs
for unresolved review threads."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Scan PRs for unresolved threads", activeForm="Scanning PRs")`
2. `TaskCreate(subject="Classify and group findings", activeForm="Classifying findings")`
3. `TaskCreate(subject="Create follow-up issues", activeForm="Creating issues")`
4. `TaskCreate(subject="Post audit trail comments", activeForm="Posting audit trail")`

## Overview

Audits closed/merged PRs for unresolved review comment threads
— legitimate feedback (security, race conditions, dead code)
that silently accumulates as tech debt after PR merge.

**Workflow:**
1. Scan merged PRs for unresolved threads (REST API)
2. Group findings by theme (security, error handling, etc.)
3. Create follow-up issues (one per group) with PR references
4. Post audit trail comments on PRs (`GH-NNN PR Audit` marker)
5. Skip already-audited PRs on re-runs (idempotent)

## Arguments

- No args — scan all merged PRs in current repo
- `--repo owner/repo` — target a specific repo
- `--limit N` — max PRs to scan (default: 200)
- `--dry-run` — show findings without creating issues

## Workflow

### Step 1: Scan PRs for Unresolved Threads

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-doctor/scripts/gh-unresolved-threads.py \
  --repo <repo> --limit <N> [--dry-run]
```

The script:
- Fetches merged PRs via REST API (respects 5000 call budget)
- For each PR, queries GraphQL `reviewThreads` for `isResolved`
- Skips PRs with `GH-NNN PR Audit` marker in comments
- Filters unresolved threads via GraphQL `isResolved` field
- Outputs JSON: `{pr_number, title, threads: [{path, body, author}]}`

### Step 2: Classify and Group Findings

Read the scan output and group unresolved threads by theme:

| Theme | Indicators |
|-------|-----------|
| Security | auth, permission, injection, XSS, CSRF |
| Error handling | exception, error, try/catch, fallback |
| Type safety | type, annotation, Any, cast, typing |
| Dead code | unused, deprecated, remove, cleanup |
| Performance | N+1, query, index, cache, optimize |
| Architecture | coupling, dependency, circular, layer |
| Testing | test, coverage, mock, fixture, assert |
| Other | anything not matching above |

Present grouped findings to the user.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Create issues (Recommended) — one issue per theme group
- Edit grouping — reclassify before creating
- Dry run — show what would be created, no side effects

### Step 3: Create Follow-Up Issues

For each theme group with findings:

```bash
gh issue create --repo <repo> \
  --title "PR Audit: <theme> findings (<count> threads)" \
  --body "<formatted findings with PR links>"
```

Issue body format:
```markdown
## PR Audit: <Theme>

Unresolved review threads found during automated PR audit.

| PR | File | Thread | Author |
|----|------|--------|--------|
| #N | path/file.py | Summary of comment | @author |

### Source PRs
- #N: PR title
- #M: PR title
```

### Step 4: Post Audit Trail Comments

For each audited PR, post a comment marking it as audited:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-doctor/scripts/gh-audit-comment.py \
  --repo <repo> --mapping <issues-json>
```

Comment format:
```
GH-NNN PR Audit — unresolved threads tracked in:
- #X: Security findings
- #Y: Error handling findings
```

This marker enables incremental re-runs — already-audited PRs
are skipped on subsequent invocations.

### Step 5: Verify Audit Completion

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-doctor/scripts/gh-audit-check.py \
  --repo <repo>
```

Reports:
- Total PRs scanned
- PRs with findings vs clean
- Issues created
- PRs marked with audit trail

## Rate Limit Awareness

- REST API: 5000 calls/hour (separate from GraphQL)
- GraphQL: 5000 points/hour
- Each PR scan uses ~3 REST calls + 1 GraphQL query
- Default limit of 200 PRs uses ~500-800 API calls
- Script reports remaining rate limit after completion

## Integration

Can be invoked standalone or as part of a maintenance workflow:
- Run periodically to catch accumulating tech debt
- Integrate with `Dev10x:fanout` to process findings
- Follow up with `Dev10x:work-on` per created issue
