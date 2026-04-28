---
name: Dev10x:ticket-branch
description: >
  Create a properly named git branch for a ticket following project
  conventions (username/TICKET-ID/[worktree/]short-slug). Ensures
  latest develop is pulled before creating the branch. Automatically
  detects worktrees and includes worktree name in branch.
  TRIGGER when: starting work on a ticket and need a feature branch.
  DO NOT TRIGGER when: branch already exists for this ticket, or
  creating a worktree (use Dev10x:git-worktree which creates branches
  internally).
user-invocable: true
invocation-name: Dev10x:ticket-branch
allowed-tools:
  - Bash(git status:*)
  - Bash(git fetch:*)
  - Bash(git checkout:*)
  - Bash(git pull:*)
  - Bash(git worktree list:*)
  - Bash(git rev-parse:*)
  - Bash(git config:*)
  - Bash(pwd:*)
  - Bash(grep:*)
---

# Create Git Branch for Ticket

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create ticket branch", activeForm="Creating branch")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

This skill creates a properly named git branch following the project convention:
- **Regular repo**: `username/TICKET-ID/short-slug`
- **Worktree**: `username/TICKET-ID/worktree-name/short-slug`

It ensures you're on the latest develop branch before creating the new branch and automatically detects if running in a git worktree.

## When to Use This Skill

Use this skill when:
- Starting work on a new ticket/issue
- Need to create a feature branch with proper naming convention
- Want to ensure you're branching from latest develop
- Have a ticket ID and title ready

## Input Requirements

This skill requires:
1. **Ticket ID** - The ticket identifier (e.g., "PAY-133", "ENG-42")
2. **Ticket Title** - The ticket title to generate slug from (e.g., "Fix MotorTimeoutException in payment processing")

## Workflow

### Step 1: Validate Current Git State

Check the current git status and warn if there are uncommitted changes:

```bash
git status --porcelain
```

**If there are uncommitted changes:**
- Warn the user: "You have uncommitted changes. Please commit or stash them before creating a new branch."
- Ask if they want to continue anyway
- If no, stop the workflow

### Step 2: Update to Latest Develop

Ensure we're working from the latest develop branch:

**Standard repo:**
```bash
git fetch origin develop
git checkout develop
git pull origin develop
```

**Worktree** (develop is checked out in the main repo):
```bash
git fetch origin develop
# Cannot checkout develop — it's used by the main worktree.
# Branch directly from origin/develop in Step 6 instead:
#   git checkout -b <branch> origin/develop
```

**Error handling:**
- If `git checkout develop` fails because develop is checked out elsewhere
  (worktree), skip checkout and branch from `origin/develop` in Step 6
- If `git pull` fails (e.g., merge conflicts), inform the user and stop
- Both errors should provide clear guidance on how to resolve

### Step 3: Generate Branch Slug

Transform the ticket title into a URL-friendly slug:

**Rules:**
1. Convert to lowercase
2. Replace spaces with hyphens
3. Remove special characters (keep only alphanumeric and hyphens)
4. Limit to 3-4 words maximum for brevity
5. Remove common words like "a", "the", "in", "for", "with" unless essential

**Examples:**
- "Fix MotorTimeoutException in payment processing" → `fix-motor-timeout`
- "Add retry mechanism for Square API calls" → `add-retry-mechanism`
- "Update customer search indexing algorithm" → `update-search-indexing`
- "Remove deprecated payment gateway" → `remove-deprecated-gateway`
- "Refactor invoice generation service" → `refactor-invoice-generation`

**Implementation approach:**
```python
# Pseudo-code for slug generation
title = "Fix MotorTimeoutException in payment processing"
words = title.lower().split()
# Remove common words
significant_words = [w for w in words if w not in ['a', 'the', 'in', 'for', 'with', 'of', 'to', 'and']]
# Take first 3-4 words
slug_words = significant_words[:4]
# Clean and join
slug = '-'.join(slug_words).replace('[^a-z0-9-]', '')
```

### Step 4: Detect Worktree (if applicable)

Detect whether we're in a worktree and extract its name.

**Primary: CWD-based detection** (no subshell, no permission friction):

Split the current working directory on `.worktrees/` and take the
first path segment after it. Example: `/work/example/.worktrees/app-pos-7/`
yields `app-pos-7`.

```bash
pwd | grep -oP '\.worktrees/\K[^/]+'
```

**Fallback: git subshell** (only when CWD is not under `.worktrees/`):

```bash
if [ -f .git ]; then
  worktree_name=$(basename "$(git rev-parse --show-toplevel)")
fi
```

**Detection rules:**
1. If CWD contains `.worktrees/` → extract name from path (primary)
2. Else if `.git` is a **file** → use git subshell fallback
3. Else (`.git` is a directory) → main repo, no worktree prefix

### Step 5: Generate Branch Name

Combine username, ticket ID, optional worktree name, and slug:

**Format:**
- Regular repo: `username/TICKET-ID/slug`
- Worktree: `username/TICKET-ID/worktree-name/slug`

**Get current username:**
```bash
git config user.name | tr '[:upper:]' '[:lower:]' | tr ' ' '-'
```

Or use a default based on the git remote URL if available.

**Branch name assembly:**
```bash
username="janusz"
ticket_id="PAY-133"
slug="fix-motor-timeout"

if [ -n "$worktree_name" ]; then
  branch="${username}/${ticket_id}/${worktree_name}/${slug}"
else
  branch="${username}/${ticket_id}/${slug}"
fi
```

**Example outputs:**

Regular repo:
- `janusz/PAY-133/fix-motor-timeout`
- `janusz/ENG-42/add-retry-mechanism`

Worktree (e.g., in `/work/example/.worktrees/app-pos-7`):
- `janusz/PAY-133/app-pos-7/fix-motor-timeout`
- `janusz/ENG-42/app-pos-7/add-retry-mechanism`
- `janusz/PAY-200/app-pos-7/update-search-indexing`

### Step 6: Create the Branch

This skill IS the project wrapper for branch creation — the raw
`git checkout -b` calls below are the implementation, not user-facing
guidance. Other skills MUST delegate to `Skill(Dev10x:ticket-branch)`
rather than embedding `git checkout -b` directly (see Skill Routing
Enforcement in `skills/work-on/instructions.md`). The cli-friction
scanner exempts this skill via the `GIT_IMPLEMENTERS` allowlist in
`src/dev10x/skills/audit/cli_friction.py`.

```bash
git checkout -b username/TICKET-ID/slug
# or for worktree:
git checkout -b username/TICKET-ID/worktree-name/slug
```

**Error handling:**
- If branch already exists, inform user and ask if they want to check it out
- If creation fails for other reasons, report the error

### Step 7: Confirm Success

Display a success message with the branch name:

```
Created and checked out branch: janusz/PAY-133/app-pos-7/fix-motor-timeout

Branch details:
- Base: develop (commit abc1234)
- Pattern: username/TICKET-ID/worktree-name/slug
- Worktree: app-pos-7
- Ready for work!
```

For regular repos (no worktree):
```
Created and checked out branch: janusz/PAY-133/fix-motor-timeout

Branch details:
- Base: develop (commit abc1234)
- Pattern: username/TICKET-ID/slug
- Ready for work!
```

## Important Notes

- Always validate git state before making changes
- Ensure develop is up-to-date to avoid merge conflicts later
- Keep slugs short and meaningful (3-4 words max)
- Handle errors gracefully with clear user guidance
- Don't force operations - confirm with user when there are issues
- **Worktree detection**: Always check if running in a worktree and include the worktree name in the branch
- Worktree name should be placed between the ticket ID and the slug (e.g., `janusz/PAY-133/app-pos-7/slug`)
- **Terminal title**: The Konsole tab title and statusline show the ticket ID from the branch name. The title updates on session start, so mid-session branch switches won't refresh it automatically.
- **Never `git -C <path>`** (GH-760 F5): `git -C` breaks
  allow-rule matching in `settings.local.json`. The CWD is
  always set correctly — run git commands without `-C`.

## Example Usage

### Example 1: Basic usage (regular repo)

**User request:**
```
Create branch for PAY-133: Fix MotorTimeoutException in payment processing
```

**Current state:** Working in main repo (not a worktree)

**Workflow execution:**
1. Check git status (clean)
2. Fetch and pull latest develop
3. Generate slug: `fix-motor-timeout`
4. Detect worktree: `.git` is a directory → not a worktree
5. Get username: `janusz`
6. Create branch: `janusz/PAY-133/fix-motor-timeout`
7. Confirm success

**Result:**
```
Created and checked out branch: janusz/PAY-133/fix-motor-timeout
```

### Example 2: Worktree usage

**User request:**
```
Create branch for PAY-133: Fix MotorTimeoutException in payment processing
```

**Current state:** Working in `/work/example/.worktrees/app-pos-7` (a worktree)

**Workflow execution:**
1. Check git status (clean)
2. Fetch and pull latest develop
3. Generate slug: `fix-motor-timeout`
4. Detect worktree: `.git` is a file → worktree detected
5. Extract worktree name: `app-pos-7`
6. Get username: `janusz`
7. Create branch: `janusz/PAY-133/app-pos-7/fix-motor-timeout`
8. Confirm success

**Result:**
```
Created and checked out branch: janusz/PAY-133/app-pos-7/fix-motor-timeout

Branch details:
- Base: develop (commit abc1234)
- Pattern: username/TICKET-ID/worktree-name/slug
- Worktree: app-pos-7
- Ready for work!
```

### Example 3: With uncommitted changes

**User request:**
```
Create branch for ENG-42: Add retry mechanism for Square API
```

**Current state:** Uncommitted changes in working directory

**Workflow execution:**
1. Check git status (finds uncommitted changes)
2. Warn user: "You have uncommitted changes. Please commit or stash them first."
3. Ask if they want to continue
4. If yes, proceed with branch creation
5. If no, stop workflow

### Example 4: Branch already exists

**User request:**
```
Create branch for PAY-100: Update customer search
```

**Current state:** Branch `janusz/PAY-100/app-pos-7/update-customer-search` already exists (in worktree)

**Workflow execution:**
1. Check git status (clean)
2. Fetch and pull latest develop
3. Detect worktree: `app-pos-7`
4. Attempt to create branch
5. Detect branch exists
6. Ask user: "Branch janusz/PAY-100/app-pos-7/update-customer-search already exists. Would you like to check it out?"
7. If yes, `git checkout janusz/PAY-100/app-pos-7/update-customer-search`
8. If no, stop workflow

## Integration with Other Skills

This skill is designed to be used standalone or as part of larger workflows:

- **Dev10x:work-on**: Uses this skill for Step 4 (Create Git Branch)
- **commit:to-new-ticket**: Could use this skill to create branch before cherry-picking

When integrating, pass the ticket ID and title as parameters.
