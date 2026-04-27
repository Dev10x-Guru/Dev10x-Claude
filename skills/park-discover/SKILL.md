---
name: Dev10x:park-discover
description: >
  Gather deferred items across all sources — so nothing is missed
  when starting a session or picking up where you left off.
  TRIGGER when: starting a session, picking up prior work, or checking
  for deferred items.
  DO NOT TRIGGER when: mid-session active work with no need to check
  deferred items.
user-invocable: true
invocation-name: Dev10x:park-discover
allowed-tools:
  - Bash(gh pr view:*)
  - Bash(gh pr list:*)
  - Bash(jq:*)
  - mcp__claude_ai_Slack__slack_search_public_and_private
---

# Dev10x:park-discover — Gather Deferred Items

**Announce:** "Using Dev10x:park-discover to check all deferral sources."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Discover deferred items", activeForm="Discovering items")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## When to Use

Invoke this skill when the user asks about existing deferred items:
- "what's deferred"
- "any open items from yesterday"
- "what do we have to pick up"
- "check for deferrals"

Do NOT use for writing new deferrals — use `Dev10x:park-todo` or
`Dev10x:park` instead.

## Workflow

### 1. Detect context

```bash
date +%Y-%m-%d
git branch --show-current
basename "$(git rev-parse --show-toplevel)"
```

Determine the lookback date: default is yesterday. If the user
specifies a date or range, use that instead.

### 2. Check all deferral sources

Run all checks in parallel where possible. Report findings grouped
by source.

#### 2a. Project TODO file

Read `.claude/TODO.md` in the repo root. Extract pending items
(`- [ ]` lines). If the file doesn't exist, note "No project TODO
file."

#### 2b. Recent code TODOs

Grep for TODO/FIXME comments in `src/`:

```bash
grep -rn "TODO\|FIXME" src/ --include="*.py" | head -30
```

Distinguish long-standing tech debt from recently added items by
checking `git log` for the lookback period.

#### 2c. Slack DM reminders

Search for bot-sent reminders using MCP Slack tools (read mode):

```
mcp__claude_ai_Slack__slack_search_public_and_private
  query: "from:<@U0AD92X4X1S> 🔖 after:LOOKBACK_DATE"
  include_bots: true
  sort: timestamp
  sort_dir: desc
  limit: 20
```

The `🔖` emoji is the standard prefix from `Dev10x:park-remind`.

If no results with `🔖`, broaden to:
```
from:<@U0AD92X4X1S> after:LOOKBACK_DATE defer OR TODO OR reminder
```

#### 2d. Memory files

Grep the global memory directory for in-progress or deferred items:

```bash
grep -rn "defer\|TODO\|in-progress\|pick up" \
  ~/.claude/memory/ \
  --include="*.md" || true
```

#### 2e. Git log (recent commits)

Check for recent commits by the user in the lookback period:

```bash
git log --all --since="LOOKBACK_DATE" --oneline --author="<username>" \
  | head -20
```

This provides context on what was being worked on.

#### 2f. PR wrap-up reminders

Check open PRs for automated session bookmark comments posted by
`Dev10x:session-wrap-up`. These are self-reminders left on PRs during
previous sessions:

```bash
gh pr list --author="@me" --state open \
  --json number,title,url --limit 10
```

For each PR, search for reminder comments with the standard prefix:

```bash
gh pr view {N} --json comments --jq '.comments[]
  | select(.body | test("🔖 \\*\\*Session bookmark\\*\\*"))
  | {body: .body[0:300], createdAt: .createdAt}'
```

The `🔖 **Session bookmark**` prefix is the standard marker set by
`Dev10x:session-wrap-up`. Include matching comments in the findings under
"### PR Session Bookmarks".

### 3. Present findings

Group results by source in a scannable format:

```markdown
## Deferred Items — [project name]

### .claude/TODO.md
(items or "No project TODO file")

### Slack DM Reminders
(items or "None found")

### Recent Code TODOs
(items or "Only long-standing tech debt")

### Memory Notes
(items or "None")

### Recent Activity (context)
(recent commits or "No commits in lookback period")

### PR Session Bookmarks
(matching PR comments or "None found")
```

### 4. Offer next steps

If deferred items were found, ask:
- "Want to start working on any of these?"
- "Want me to check other repos too?" (if multi-repo context)

## Used By

- `Dev10x:park-todo` — redirects here when user asks to review/check
  deferrals instead of write them
