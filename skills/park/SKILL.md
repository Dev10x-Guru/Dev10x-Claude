---
name: Dev10x:park
description: >
  Smart deferral router — saves tasks for later to the right place
  (PR, ticket, code, Slack, or session.yaml task index) so they
  are actually rediscovered instead of being forgotten.
  TRIGGER when: a task should be saved for later instead of done now.
  DO NOT TRIGGER when: task should be done now, or specifically
  deferring to code (use Dev10x:park-todo) or Slack (use
  Dev10x:park-remind).
user-invocable: true
invocation-name: Dev10x:park
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(git branch:*)
  - Bash(git rev-parse:*)
  - Bash(git log:*)
  - mcp__plugin_Dev10x_cli__pr_comments
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__pr_issue_comment
  - mcp__plugin_Dev10x_cli__issue_comment_edit
  - mcp__plugin_Dev10x_cli__mktmp
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
invoked standalone or called by `Dev10x:session-wrap-up` for each open
loop.

Every routed deferral that has a local representation also lands as
an entry in `.claude/Dev10x/session.yaml` `tasks:` with a `source:`
field that names the target (GH-85). This guarantees
`Dev10x:park-discover` can surface the item without scanning every
write path.

## Workflow

### 1. Receive item

Accept the item to defer. This is either:
- Passed from `Dev10x:session-wrap-up` (structured)
- Provided by user directly: `/Dev10x:park "item description"`

### 2. Detect context

Run these checks to determine available targets. Each is a single
Bash call — no `;` chaining, no subshells inside command strings.

**Branch:**
```bash
git branch --show-current
```

Extract ticket ID from the branch name (pattern:
`username/TICKET-ID/[worktree/]desc`).

**Repository toplevel:**
```bash
git rev-parse --show-toplevel
```

**Open PR:**
```
mcp__plugin_Dev10x_cli__pr_detect(arg="")
```

The MCP wrapper auto-detects the PR for the current branch. Treat
an `{"error": ...}` response as "no open PR" rather than a failure.

### 3. Present targets

Build target list based on detected context. Always available:

| # | Target | When it surfaces |
|---|--------|-----------------|
| 1 | session.yaml task index | Next `Dev10x:park-discover` run |
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
| session.yaml task index | Append entry with `source: park` (see § Session.yaml Append) |
| Slack DM | Invoke `Dev10x:park-remind` (which also appends `source: slack-reminder`) |
| Create issue | Ask user which tracker (Linear, GitHub Issues, Jira, etc.) then create the issue with the deferred item as description; also append a `source: park` entry pointing at the new issue URL |
| Issue tracker comment | Post comment via the appropriate tracker MCP or CLI tool; also append a `source: park` entry pointing at the comment URL |
| PR comment | Post as PR comment (simple format); also append a `source: park` entry with the PR URL |
| PR session bookmark | Post as PR comment with rich metadata (see PR Bookmark Format below); also append a `source: pr-bookmark` entry with the PR URL + comment ID |
| Inline TODO/FIXME | Invoke `Dev10x:park-todo` (inline mode) — ask user for file path if not provided |
| Keep in session | Invoke `Dev10x:session-tasks` to create a TaskCreate entry |

### 5. Session.yaml Append

The schema for a `park`-sourced task entry mirrors the one in
`Dev10x:park-todo` § Session.yaml Append:

```yaml
- subject: <one-line description>
  status: pending
  source: <park | pr-bookmark>
  created_at: <YYYY-MM-DD>
  metadata:
    branch: <current-branch>
    pr_url: <url>         # when target is PR comment / bookmark
    comment_id: <id>      # when target is PR comment / bookmark
    issue_url: <url>      # when target creates an issue
```

Read the existing session.yaml, append the entry to the end of
the `tasks:` list, then write back. Never overwrite
`friction_level`, `active_modes`, `continuation_prompt`, or
`insights`.

### 6. Confirm

Report which targets received the item AND confirm the
session.yaml index entry:

```
Deferred "Add order confirmation email":
  ✓ session.yaml task index (source: park)
  ✓ Slack DM sent (source: slack-reminder)
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

1. **Session ID** — extract from the current JSONL filename
2. **Review threads** — list root comments and their status via:
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

Compose the comment body in memory (or via the mktmp wrapper if
the body needs an intermediate file), then post it via the MCP
wrapper:

```
mcp__plugin_Dev10x_cli__pr_issue_comment(pr_number=<number>, body=<composed-body>)
```

The wrapper returns the new comment's `id` and `html_url`. Store
the `id` in the session.yaml entry's `metadata.comment_id` so the
bookmark can be edited later without re-detecting the comment.

To **update** an existing bookmark comment instead of creating a
new one, edit by `comment_id`:

```
mcp__plugin_Dev10x_cli__issue_comment_edit(comment_id=<id>, body=<new-body>)
```

## Used By

- `Dev10x:session-wrap-up` — Phase 3 calls this for each deferred item
- `Dev10x:gh-pr-bookmark` — thin wrapper that pre-selects PR session bookmark target
