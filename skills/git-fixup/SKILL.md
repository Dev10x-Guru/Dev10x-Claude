---
name: Dev10x:git-fixup
description: >
  Create a fixup! commit for a PR review comment or standalone
  improvement. Enforces one fixup per comment thread when linked to
  a review.
  TRIGGER when: creating a fixup! commit for a review finding or
  standalone improvement.
  DO NOT TRIGGER when: creating a regular commit (use Dev10x:git-commit),
  or implementing PR fixes with push and reply (use Dev10x:gh-pr-fixup).
user-invocable: true
invocation-name: Dev10x:git-fixup
allowed-tools:
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Write(/tmp/Dev10x/git/**)
  - Bash(gh repo view:*)
  - Bash(gh api:*)
  - mcp__plugin_Dev10x_cli__push_safe
---

# Create Fixup Commit

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create fixup commit", activeForm="Creating fixup")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

This skill creates properly scoped `fixup!` commits. Two modes:

1. **Review fixup** — addresses a specific PR review comment (one fixup per
   comment thread, comment link required in body)
2. **Standalone fixup** — self-initiated improvement not tied to a review
   comment (marked with `Standalone fixup` in body)

Why fixup commits?
- Reviewers can verify each fix individually
- Easy to match "comment → fixup commit"
- `git rebase -i --autosquash` squashes them into the target commit

## When to Use This Skill

- Called by `Dev10x:gh-pr-fixup` when addressing review comments
- When you need to create a fixup commit for a specific review comment
- When you need a standalone fixup for a self-initiated improvement
- **When you fix a bug or anti-pattern that belongs to a prior commit in the branch** — use `Dev10x:git-fixup` immediately rather than a standalone commit that would need converting later
- NOT for general commits (use `Dev10x:git-commit` skill instead)

## Input Requirements

| Parameter | Required | Description |
|-----------|----------|-------------|
| `pr_number` | No | The pull request number (omit for standalone) |
| `comment_id` | No | The GitHub comment ID being addressed |
| `repository` | No | Owner/repo (defaults to current repo) |

If neither `pr_number` nor `comment_id` is provided, prompt the user to
confirm this is a standalone fixup before proceeding.

## Workflow

### Step 0: Verify CWD is the target repository

**REQUIRED: Before any git operation**, verify the working
directory matches the expected repository:

```bash
git rev-parse --show-toplevel
```

Compare the output against the expected repo path. If they
differ, **STOP** — do not use `git -C` as a workaround. Instead:
- If in a worktree setup, call `EnterWorktree` to switch to the
  correct worktree first
- If the repo is not checked out, inform the caller

This prevents the cascade of `git -C` usage that follows when
the CWD is wrong. The `git -C` flag is **NEVER permitted** in
this skill (see Important Notes).

### Step 1: Determine Mode

If a comment ID or PR comment URL was provided → **review fixup** mode.

If the invocation args include a **target commit SHA + description** (e.g.
`/Dev10x:git-fixup abc1234 Fix null handling in phone lookup`), intent is clear —
proceed directly in **standalone fixup** mode without asking.

Otherwise, use `AskUserQuestion` to ask:

> "No review comment provided. Create a standalone fixup?"

Options: "Yes, standalone fixup" / "No, use /Dev10x:git-commit instead"

If the user confirms → **standalone fixup** mode.
If the user declines → suggest using `/Dev10x:git-commit` instead.

### Step 2: Fetch Comment Details (review fixup only)

Skip this step entirely for standalone fixups.

```bash
# Get repository info
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
OWNER=$(echo $REPO | cut -d'/' -f1)
REPO_NAME=$(echo $REPO | cut -d'/' -f2)

# Fetch the comment
gh api repos/{owner}/{repo}/pulls/comments/{comment_id}
```

Extract from comment:
- `path` - File the comment is on
- `line` / `original_line` - Line number context
- `diff_hunk` - Code context
- `html_url` - Link to comment thread (for commit body)
- `body` - The review comment text

### Step 3: Identify Original Commit

Find the commit this fixup should target:

```bash
# Detect base branch dynamically
BASE_BRANCH=$(git show-ref --verify --quiet refs/heads/develop \
  && echo develop || echo master)
ORIGINAL_COMMIT=$(git log ${BASE_BRANCH}..HEAD --reverse --format="%H" | head -1)
ORIGINAL_MESSAGE=$(git log --format=%s -1 $ORIGINAL_COMMIT)
```

### Step 4: Validate Staged Changes

**Check what's staged:**
```bash
git diff --cached --name-only
```

**Validation rules:**
1. At least one file must be staged
2. Staged files should relate to the comment's file path
3. Warn if staging files unrelated to the comment

**If unrelated files are staged:**
```
Warning: The following staged files may be unrelated to comment on {path}:
- {unrelated_file_1}
- {unrelated_file_2}

Continue anyway? (y/n)
```

### Step 5: Build Commit Message

**Review fixup format:**
```
fixup! {original_commit_message}

Addresses review comment:
{comment_html_url}
```

**Standalone fixup format:**
```
fixup! {original_commit_message}

Standalone fixup
{description of what this fixes and why}
```

**Review fixup example:**
```
fixup! ✅ QA-159 add E2E tests for customer required before payment

Addresses review comment:
https://github.com/example-org/app-e2e/pull/269#discussion_r2706078039
```

**Standalone fixup example:**
```
fixup! ✨ PAY-518 Return make, model and VIN in trim lookups

Standalone fixup
Remove duplicate flat attributes and encapsulate data
in PosSubModelNode for cohesion.
```

### Step 6: Create the Commit

**IMPORTANT:** Never use `cat <<EOF` or heredoc syntax — the
`validate-bash-security.py` hook blocks it. Use Write tool + `git commit -F`.

Create a unique temp file via `mktemp` to avoid cross-session collisions:
```bash
/tmp/Dev10x/bin/mktmp.sh git fixup-msg .txt
```
Store the returned path for subsequent steps.

**Review fixup:**
```bash
# 1. Write message to the unique temp file (use Write tool, NOT echo/cat)
Write "<unique-path>" with:
  fixup! {ORIGINAL_MESSAGE}

  Addresses review comment:
  {COMMENT_URL}

# 2. Commit with -F
git commit -F <unique-path>
```

**Standalone fixup:**
```bash
# 1. Write message to the unique temp file (use Write tool)
Write "<unique-path>" with:
  fixup! {ORIGINAL_MESSAGE}

  Standalone fixup
  {DESCRIPTION}

# 2. Commit with -F
git commit -F <unique-path>
```

### Step 7: Verify and Return

```bash
# Get the new commit hash
COMMIT_HASH=$(git rev-parse --short HEAD)
FULL_HASH=$(git rev-parse HEAD)

# Use PR-based URL when PR number is available (review fixup mode).
# PR-based URLs (pull/NUMBER/commits/HASH) let reviewers comment on
# the diff within the PR context. Standalone /commit/HASH URLs create
# comments disconnected from the PR review thread.
if [ -n "${PR_NUMBER:-}" ]; then
  COMMIT_URL="https://github.com/${REPO}/pull/${PR_NUMBER}/commits/${FULL_HASH}"
else
  COMMIT_URL="https://github.com/${REPO}/commit/${FULL_HASH}"
fi

echo "Created fixup commit: ${COMMIT_HASH}"
echo "URL: ${COMMIT_URL}"
```

**Completion:** Signal completion silently via `TaskUpdate`
(status="completed"). Do not output "Returning to caller"
messages — they mislead users in nested skill execution into
thinking the workflow is done when the parent still has steps.

The caller reads these values from git state:
- `commit_hash` — `git rev-parse --short HEAD`
- `commit_url` — constructed from repo + PR number + full hash

## Pre-commit Hook Integration

This skill works with the `check-fixup-comment-link` pre-commit hook which validates:

1. If commit message starts with `fixup!`
2. Body must contain either:
   - Exactly ONE GitHub comment thread link, OR
   - The `Standalone fixup` marker
3. Link format: `https://github.com/{owner}/{repo}/pull/{pr}#discussion_r{id}`

The hook will **reject** fixup commits that:
- Have neither a comment link nor a `Standalone fixup` marker
- Have multiple comment links (violates one-fixup-per-comment rule)

## Error Handling

### No Staged Changes
```
Error: No changes staged for commit.
Stage changes first with: git add {file}
```

### Comment Not Found
```
Error: Could not fetch comment {comment_id}.
Verify the comment ID and repository.
```

### Pre-commit Hook Rejection
```
Error: Fixup commit must reference exactly one comment thread.

Your commit body should contain a line like:
https://github.com/owner/repo/pull/123#discussion_r456789

This links the fixup to the specific review comment it addresses.
```

## Integration with Dev10x:gh-pr-fixup

The `Dev10x:gh-pr-fixup` skill calls this skill instead of creating commits
directly:

```
Dev10x:gh-pr-fixup workflow:
1. Analyze comment
2. Implement fix
3. Stage changes: git add {file}
4. Call Dev10x:git-fixup with (pr_number, comment_id)  <-- uses this skill
5. Push: mcp__plugin_Dev10x_cli__push_safe
6. Reply to comment with commit reference
```

## Important Notes

- **One fixup per comment** — enforced by pre-commit hook (review mode)
- **Comment link or standalone marker required** — enables traceability
- **Scoped changes** — warns about unrelated files (review mode)
- **Works with autosquash** — `git rebase -i --autosquash` will squash these
- **Prompt before standalone** — use `AskUserQuestion` to confirm; never
  silently proceed in standalone mode
- **Always use plain `git`** — NEVER use `git -C <path>`. The session CWD is
  already the repo. `git -C` creates duplicate allow-rules in settings.local.json
  and will require permission prompts after a fresh start.

## Example Usage

### Review fixup (called by Dev10x:gh-pr-fixup)

```bash
# Stage the fix
git add tests/pages/crm.py

# Create fixup — skill fetches comment and builds message
# Input: comment URL or PR 269, comment 2706078039
```

**Result:**
```
fixup! ✅ QA-159 add E2E tests for customer required before payment

Addresses review comment:
https://github.com/example-org/app-e2e/pull/269#discussion_r2706078039
```

### Standalone fixup (self-initiated improvement)

```bash
# Stage the fix
git add src/app_pos/motor/api/nodes.py

# Invoke /Dev10x:git-fixup with no comment argument
# Claude asks: "No review comment provided. Create a standalone fixup?"
# User confirms → standalone mode
```

**Result:**
```
fixup! ✨ PAY-518 Return make, model and VIN in trim lookups

Standalone fixup
Remove duplicate flat attributes and encapsulate data
in PosSubModelNode for cohesion.
```
