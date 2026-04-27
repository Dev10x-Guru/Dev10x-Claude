---
name: Dev10x:park
description: >
  Smart deferral router — saves tasks for later to the right place
  (PR, ticket, code, Slack, or project TODO) so they are actually
  rediscovered instead of being forgotten.
  TRIGGER when: a task should be saved for later instead of done now.
  DO NOT TRIGGER when: task should be done now, or specifically
  deferring to code (use Dev10x:park-todo) or Slack (use
  Dev10x:park-remind).
user-invocable: true
invocation-name: Dev10x:park
allowed-tools:
  - Bash(gh pr view:*)
  - Bash(gh pr list:*)
  - Bash(gh pr comment:*)
  - Bash(gh api:*)
  - mcp__plugin_Dev10x_cli__pr_comments
  - AskUserQuestion
---

# Dev10x:park — Smart Deferral Router

**Announce:** "Using Dev10x:park to save this item for later."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Defer work item", activeForm="Deferring item")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Route a single deferred item to the right discovery context. Can be
invoked standalone or called by `Dev10x:session-wrap-up` for each open loop.

## Workflow

### 1. Receive item

Accept the item to defer. This is either:
- Passed from `Dev10x:session-wrap-up` (structured)
- Provided by user directly: `/Dev10x:park "item description"`

### 2. Detect context

Run these checks to determine available targets:

**Branch + ticket:**
```bash
git branch --show-current
```
Extract ticket ID from branch name (pattern: `username/TICKET-ID/[worktree/]desc`).

**Open PR:**
```bash
gh pr list --head "$(git branch --show-current)" --state open \
  --json number,url --limit 1
```

**Repository root:**
```bash
basename "$(git rev-parse --show-toplevel)"
```

### 3. Present targets

Build target list based on detected context. Always available:

| # | Target | When it surfaces |
|---|--------|-----------------|
| 1 | `.claude/TODO.md` | Next Claude session in this project |
| 2 | Slack DM to self | When clearing Slack messages |
| 3 | Create issue | When triaging backlog or planning sprint |

Conditionally available (include only when detected):

| # | Target | Condition |
|---|--------|-----------|
| 4 | Issue tracker comment | Ticket ID found in branch |
| 5 | PR comment | Open PR found for current branch |
| 5b | PR session bookmark | Open PR + session end / session-wrap-up context |
| 6 | Inline TODO/FIXME | User mentions a specific file |
| 7 | Keep in session | User wants to finish later this session |

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text)
with multiSelect enabled so user can pick multiple targets
for the same item.

### 4. Delegate to targets

For each selected target:

| Target | Action |
|--------|--------|
| `.claude/TODO.md` | Invoke `Dev10x:park-todo` (project file mode) |
| Slack DM | Invoke `Dev10x:park-remind` |
| Create issue | Ask user which tracker (Linear, GitHub Issues, Jira, etc.) then create the issue with the deferred item as description |
| Issue tracker comment | Post comment via the appropriate tracker MCP or CLI tool |
| PR comment | Post as PR comment (simple format) |
| PR session bookmark | Post as PR comment with rich metadata (see PR Bookmark Format below) |
| Inline TODO/FIXME | Invoke `Dev10x:park-todo` (inline mode) — ask user for file path if not provided |
| Keep in session | Invoke `Dev10x:session-tasks` to create a TaskCreate entry |

### 5. Confirm

Report which targets received the item:

```
Deferred "Add order confirmation email":
  ✓ .claude/TODO.md (project)
  ✓ Slack DM sent
```

## Formatting for External Targets

**Issue tracker comment:**
```markdown
🔖 **Deferred from session [YYYY-MM-DD]**

<item description>

_Branch: `<branch-name>`_
```

**PR comment (simple):**
```markdown
🔖 **Deferred item**

<item description>

_Session: YYYY-MM-DD_
```

**PR session bookmark (rich metadata):**

Use this format when deferring work on a PR to the next session. It
provides enough context for `claude --resume` to pick up where the
session left off.

Gather this data before composing:

1. **Session ID** — extract from the current JSONL filename:
   ```bash
   basename "$(ls -t ~/.claude/projects/<encoded-cwd>/*.jsonl | head -1)" .jsonl
   ```
2. **Review threads** — list root comments and their status:
   ```
   mcp__plugin_Dev10x_cli__pr_comments(action="list", pr_number={number})
   ```
3. **Unaddressed comments** — filter the list result for unresolved
   root comments (where `in_reply_to_id` is null)
4. **Current commit** — `git log --oneline <base-branch>..HEAD`
5. **PR body context** — `gh pr view {number} --json body -q '.body'`

Compose the comment:

```markdown
> **Automated reminder** — @{reviewer} session bookmark for
> picking up this review tomorrow.
> Session ID: `{session_id}`
> Resume with: `claude --resume {session_id}`

---

## PR #{number} Review — State of Play ({date})

### Context

{1-2 sentence summary of what the PR does}

### Review comments addressed

| Thread | Status | Key point |
|--------|--------|-----------|
| [r{id}]({url}) | Addressed / Open | {one-line summary} |

### Current state after grooming (`{short_sha}`)

{Brief description of production code and test state}

### What to do next

1. {next step}
2. {next step}
```

Write the comment to a unique temp file and post via `--body-file`:
```bash
/tmp/Dev10x/bin/mktmp.sh git pr-comment .txt
```
Write content to the returned path using Write tool, then:
```bash
gh pr comment {number} --body-file <unique-path>
```

To **update** an existing bookmark comment instead of creating a new one:
```bash
gh api repos/{owner}/{repo}/issues/comments/{comment_id} \
  -X PATCH -F body=@<unique-path>
```

## Used By

- `Dev10x:session-wrap-up` — Phase 3 calls this for each deferred item
- `Dev10x:gh-pr-bookmark` — thin wrapper that pre-selects PR session bookmark target
