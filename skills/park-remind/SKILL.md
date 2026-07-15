---
name: Dev10x:park-remind
description: >
  Schedule a Slack reminder — so deferred items appear when you are
  clearing messages, not buried in a file you might not open.
  TRIGGER when: deferring work that should resurface via Slack
  notification later.
  DO NOT TRIGGER when: deferring to code or project storage (use
  Dev10x:park-todo), or routing to the best destination automatically
  (use Dev10x:park).
user-invocable: true
invocation-name: Dev10x:park-remind
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Bash(git branch:*)
  - Bash(git rev-parse:*)
  - mcp__plugin_Dev10x_cli__mktmp
  - Edit(/tmp/Dev10x/slack/**)
---

# Dev10x:park-remind — Slack DM Reminder

**Announce:** "Using Dev10x:park-remind to send a Slack reminder to yourself."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Schedule Slack reminder", activeForm="Scheduling reminder")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Send a self-DM via Slack with a deferred item, formatted with session
context so you know where to pick it up. After the DM is sent, append
a pointer entry to `.claude/Dev10x/session.yaml` so
`Dev10x:park-discover` can surface it locally without a Slack search
(GH-85).

## Prerequisites

- Slack token available (env `SLACK_TOKEN` or system keyring)
- `slack-notify.py` accessible at `${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py`

## Workflow

### 1. Gather context

```bash
git branch --show-current
```

```bash
git rev-parse --show-toplevel
```

Each in a single Bash call — no `;` chaining, no subshells.
Extract from the branch name:
- Ticket ID (pattern: `username/TICKET-ID/[worktree/]description`)
- Project name (from the toplevel basename)

### 2. Format message

Build the reminder message:

```
🔖 Deferred from session [YYYY-MM-DD]
Project: <project-name> | Branch: <branch-name>

<user's deferred item text>
```

If the user provided a URL or file reference, include it on a
separate line after the item text.

### 3. Send DM

For multi-line messages, write the formatted text to a unique temp file
using the Write tool first, then pass it via command substitution:

```
mcp__plugin_Dev10x_cli__mktmp(namespace="slack", prefix="remind-msg", ext=".txt")
```

Write content to the returned path using Write tool, then:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py \
  --remind "$(cat <unique-path>)"
```

Do NOT use heredoc (`cat <<'EOF'`) to build the message inline —
the bash security hook blocks it. Always use Write tool → temp file
→ `$(cat ...)` for multi-line content.

### 4. Append to session.yaml

After Slack confirms delivery, append a pointer entry to the
session.yaml `tasks:` list using the schema documented in
`Dev10x:park-todo` § Session.yaml Append:

```yaml
- subject: <item text, single line>
  status: pending
  source: slack-reminder
  created_at: <YYYY-MM-DD>
  metadata:
    branch: <current-branch>
    slack_ts: <timestamp returned by slack-notify>
    slack_permalink: <permalink returned by slack-notify>
```

The Slack DM remains the authoritative content; the session.yaml
entry is the local index that `Dev10x:park-discover` reads
without a network round-trip.

If session.yaml does not exist, create it with the new entry
under `tasks:` while preserving any sibling fields. Never
overwrite `friction_level`, `active_modes`,
`continuation_prompt`, or `insights`.

### 5. Confirm

Report to user: "Sent reminder to your Slack DMs and indexed in
session.yaml."

## Standalone Usage

When invoked directly: `/Dev10x:park-remind "message text"`

Parse the argument as the item text. Gather context and send.

## Used By

- `Dev10x:park` — when user picks "Slack DM to self"
