---
name: Dev10x:gh-pr-fixup
description: >
  Implement a fix for a validated PR review comment, create a fixup!
  commit, push, and reply with the commit reference. Creates ONE fixup
  commit per comment.
  TRIGGER when: PR review comment has been validated as needing a code fix.
  DO NOT TRIGGER when: comment is invalid/question (use Dev10x:gh-pr-triage
  first), or creating standalone fixup without PR context (use Dev10x:git-fixup).
user-invocable: true
invocation-name: Dev10x:gh-pr-fixup
allowed-tools:
  - mcp__plugin_Dev10x_cli__pr_comment_reply
  - mcp__plugin_Dev10x_cli__pr_comments
  - Bash(gh pr comment:*)
  - Bash(gh api:*)
  - Bash(pytest:*)
  - mcp__plugin_Dev10x_cli__push_safe
---

# Implement Fix for PR Review Comment

## Overview

This skill handles implementing a fix for a PR review comment that has
already been validated as needing a code change. It:

1. Analyzes the comment to understand the requested change
2. Implements the fix in the codebase
3. Creates a `fixup!` commit targeting the original commit
4. Pushes the commit
5. Replies to the comment with the commit reference

**Critical rule: ONE fixup commit per PR comment.**

**Entry point rule:** `Dev10x:gh-pr-respond` is the recommended
entry point for all PR review comments. It orchestrates triage,
fixup, reply, and thread resolution as a pipeline. Calling
`Dev10x:gh-pr-fixup` directly skips triage, reply formatting,
and thread resolution — use it only when you have already
validated the comment and will handle reply/resolution yourself.

**When to use this skill:**
- Called by `Dev10x:gh-pr-respond` after `Dev10x:gh-pr-triage` returns `VALID`
- Standalone only when the comment is already validated and you
  will handle reply and thread resolution separately

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next.
Never pause to ask "should I continue?" between steps.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Validate review comment", activeForm="Validating comment")`
2. `TaskCreate(subject="Implement fix", activeForm="Implementing fix")`
3. `TaskCreate(subject="Create fixup commit", activeForm="Creating fixup commit")`
4. `TaskCreate(subject="Push and reply", activeForm="Pushing and replying")`

Set dependencies: implement blocked by validate, commit blocked
by implement, push blocked by commit.

## Input Requirements

1. **PR URL or Comment URL** — Full GitHub URL to the PR comment
   (e.g., `https://github.com/owner/repo/pull/123#discussion_r456`)
2. **Repository** — Owner/repo (extracted from URL or defaults to current repo)

**Optional additional context:**
- User may provide extra context after the URL
- Example: `/Dev10x:gh-pr-fixup https://...#discussion_r456 The API now provides customer_url`

## Workflow

### Step 1: Parse Input and Fetch Comment Details

**Parse the comment URL:**
```
URL format: https://github.com/{owner}/{repo}/pull/{pr_number}#discussion_r{comment_id}
```

**Fetch the comment:**
```
mcp__plugin_Dev10x_cli__pr_comments(action="get", comment_id={comment_id})
```

Extract:
- `body` — The comment text (the requested change)
- `path` — File path the comment is on
- `line` — Line number in the diff
- `original_line` — Original line number
- `diff_hunk` — The code context around the comment
- `commit_id` — The commit this comment refers to
- `user.login` — Who left the comment
- `html_url` — Direct link to comment

### Step 2: Analyze the Comment

Parse the comment to understand:

1. **Type of change requested:**
   - Code fix (bug, logic error)
   - Style/formatting issue
   - Naming improvement
   - Missing test coverage
   - Architectural suggestion

2. **Scope of change:**
   - Single line fix
   - Multi-line fix in same file
   - Changes across multiple files
   - Requires new tests

### Step 3: Check if Already Addressed

Before implementing, check if a previous fixup commit already addresses
this comment:

**Reuse existing fixup commit if:**
- The exact same code change was already made
- No additional code modifications are needed

**Create new fixup commit if:**
- Any code change is required (even small additions)
- The existing fix only partially addresses the concern

**When reusing a fixup:**
- Reply to the comment referencing the existing commit
- Tailor the reply text to address this comment's specific concern
- Skip Steps 4-6, go directly to Step 7

### Step 4: Implement the Fix

1. **Read the affected file(s):**
   ```bash
   Read tool with file_path and relevant line range
   ```

2. **Make the change:**
   - Use Edit tool for modifications
   - Follow existing code patterns
   - Maintain consistent style

3. **REQUIRED: Run tests before committing.** Do NOT skip this
   step, even for single-line fixes. Code changes across bounded
   contexts can break invariants that only tests catch.

   **Exception for non-testable files (GH-759 F4):** Changes to
   infrastructure files that have no applicable test suite may
   skip test execution with a note explaining why. Non-testable
   file types include: `.yml`/`.yaml` (CI workflows, config),
   `.md` (documentation, SKILL.md), `.toml` (pyproject, config),
   `Dockerfile`, `.json` (settings, manifests). When skipping,
   note: "Tests skipped: non-testable infrastructure file."

   **REQUIRED: Delegate to `Skill(Dev10x:py-test)` for Python
   projects — never run pytest inline.** The skill enforces
   coverage checks that bare `pytest -x` commands bypass. This
   is a repeat offender: 12 instances across 3 audit sessions
   (PAY-762, PAY-735, PAY-592). For non-Python projects, run
   the project's test runner directly (`npm test`, etc.).

   **LOOP ENFORCEMENT (GH-682):** This rule applies to EVERY
   test run in the fix-test-fix cycle, not just the first.
   When tests fail and you iterate (fix code → re-run tests →
   fix code → re-run tests), EACH re-run MUST use
   `Skill(Dev10x:py-test)`. The pattern of "first run uses
   skill, subsequent runs use raw pytest" is the #1 skill
   routing violation. Before running any test command, check:
   am I about to type `pytest` or `uv run pytest`? If yes,
   STOP and use `Skill(Dev10x:py-test)` instead.

   Note: `ruff format` and `ruff check --fix` run automatically via PostToolUse hook.

   **If tests fail:** Fix the test failure before proceeding to
   Step 5. Re-run tests via `Skill(Dev10x:py-test)` — not raw
   pytest. If the fix itself is wrong, revert and reply asking
   for clarification (see Error Handling).

### Step 5: Create Fixup Commit (delegate to Dev10x:git-fixup)

**IMPORTANT:** Delegate to the `Dev10x:git-fixup` skill.

```bash
# Stage the changes
git add {file_path}

# Delegate to Dev10x:git-fixup skill (handles message format)
```

**Fixup commit format:**
```
fixup! {original_commit_subject}

Addresses review comment:
https://github.com/{owner}/{repo}/pull/{pr}#discussion_r{comment_id}
```

### Step 6: Push the Fixup Commit

**Primary (MCP tool):** `mcp__plugin_Dev10x_cli__push_safe(args=["origin", "HEAD"])`

**Fallback:** `Skill(Dev10x:git)` for safe push with protected branch checks.

Get the commit hash and build both link types for the reply:
```bash
commit_hash=$(git rev-parse --short HEAD)
full_hash=$(git rev-parse HEAD)
# PR-relative link — most useful while the PR is in flight: clicks
# land in the inline-diff view inside the PR and reviewers can comment
# on the change without leaving the page. Becomes 404 once the commit
# vanishes (after groom, after merge with squash strategy).
pr_commit_url="https://github.com/{owner}/{repo}/pull/{pr_number}/commits/${full_hash}"
# Absolute repo permalink — survives grooming and merge: rebase
# rewrites the SHA on the branch but the original commit remains
# reachable in the repo, so the permalink stays valid post-merge.
permalink="https://github.com/{owner}/{repo}/commit/${full_hash}"
```

### Step 7: Reply to Comment Thread

Reply **in the review comment thread** (not as a top-level PR comment).

**Preferred: MCP tool** (no Bash permission friction):
```
mcp__plugin_Dev10x_cli__pr_comment_reply(
    pr_number={pr_number},
    comment_id={comment_id},
    body="Fixed in [`{short_hash}`]({pr_commit_url}) · [permalink]({permalink}) - {brief_explanation}"
)
```

**Fallback** (raw CLI):
```bash
gh api --method POST \
  repos/{owner}/{repo}/pulls/{pr_number}/comments/{comment_id}/replies \
  -f body="Fixed in [\`{short_hash}\`]({pr_commit_url}) · [permalink]({permalink}) - {brief_explanation}"
```

**Reply format (GH-777, GH-52):**
```markdown
Fixed in [`{short_hash}`]({pr_commit_url}) · [permalink]({permalink}) - {brief explanation}.
```

Both links are intentional:
- The `{short_hash}` link points at the **PR-relative** URL
  (`/pull/N/commits/HASH`) so a click during review lands inside
  the PR's inline-diff view — reviewers can comment on the change
  without navigating away. This URL 404s after groom or squash-
  merge, but that's after the review is done.
- The trailing `[permalink]` points at the **absolute repo URL**
  (`/commit/HASH`) which survives grooming and merge: useful as a
  long-lived audit trail and the only one that still resolves
  after the SHA leaves the branch tip.

**When reusing a fixup for another comment:**
- Reference the same commit
- Tailor explanation to this comment's specific concern

## Error Handling

### Fix Causes Test Failure

If the fix breaks tests:
1. Revert: `git checkout -- {file_path}`
2. Reply asking for clarification:
   ```
   The suggested change causes test failures in `test_xyz`.
   Could you clarify the expected behavior?

   Error: {brief_error_message}
   ```

### Ambiguous Comment

If the comment is unclear:
1. Do not make changes
2. Reply asking for clarification:
   ```
   Could you clarify what change you'd like here?
   I see a few possible interpretations:
   1. {interpretation_1}
   2. {interpretation_2}
   ```

### Merge Conflict

If the file has changed since the comment was made:
1. Fetch latest: `git pull --rebase`
2. Re-analyze the comment in new context
3. Implement fix on current code

## Important Notes

- **One fixup per comment** — enforced by pre-commit hook
- **Comment link required** — every fixup commit must have exactly one
  comment thread link in body
- **Reply in thread** — use `gh api` to reply in thread, never
  `gh pr comment`
- **Never force push** — always regular push for fixup commits
- **Reuse only if identical** — only reuse a fixup if zero additional
  code changes needed
- **Discover project tooling** — check `Makefile`, `package.json`,
  or repo root for project-specific scripts

## Integration

```
Dev10x:gh-pr-monitor → Dev10x:gh-pr-respond (orchestrator)
                 ├── Dev10x:gh-pr-triage
                 └── Dev10x:gh-pr-fixup  ← this skill
                      └── Dev10x:git-fixup
```

**Standalone usage:**
```bash
/Dev10x:gh-pr-fixup https://github.com/owner/repo/pull/123#discussion_r456
```

**Called by Dev10x:gh-pr-respond:**
```
Dev10x:gh-pr-respond receives comment URL
  → delegates to Dev10x:gh-pr-triage → verdict: VALID
  → delegates to Dev10x:gh-pr-fixup (this skill)
  → fix implemented, pushed, replied
```

## Tool Reference

GitHub comment operations use `gh api` for REST calls and `gh api graphql`
for thread resolution. See `references/github_api.md` for full reference.
