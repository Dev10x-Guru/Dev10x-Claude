---
name: Dev10x:investigate
description: >
  Root-cause a bug report, question, or unexpected behaviour from a
  Slack thread — posts a technical reply with GitHub links and creates
  a Linear ticket when warranted.
  TRIGGER when: given a Slack URL pointing to a bug report, question,
  or unexpected behaviour that needs investigation.
  DO NOT TRIGGER when: no Slack URL provided, issue already root-caused,
  or user wants to investigate without posting a reply.
user-invocable: true
invocation-name: Dev10x:investigate
allowed-tools:
  - AskUserQuestion
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/investigate/scripts/parse-slack-url.sh:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/investigate/scripts/reply.sh:*)
  - Skill(skill="Dev10x:ticket-create")
  - Skill(skill="pr:review")
---

# Dev10x:investigate

**Announce:** "Using Dev10x:investigate to investigate [brief description of the issue]."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next — no checkpoints under adaptive friction.
Never pause to ask "should I continue?" between steps.

**Playbook-driven modes:**
- Standard investigation (Condition: thread describes bug/question/behaviour)
  → Load `references/playbook.yaml` play "standard"
- PR review (Condition: thread contains a GitHub PR link for review)
  → Load `references/playbook.yaml` play "pr-review"

**REQUIRED: Create tasks before ANY work.** Execute `TaskCreate`
calls at startup based on the detected mode:

**Standard mode:**
1. `TaskCreate(subject="Parse Slack URL", activeForm="Parsing URL")`
2. `TaskCreate(subject="Read the thread", activeForm="Reading thread")`
3. `TaskCreate(subject="Investigate the codebase", activeForm="Investigating")`
4. `TaskCreate(subject="Verify findings", activeForm="Verifying findings")`
5. `TaskCreate(subject="Draft the reply", activeForm="Drafting reply")`
6. `TaskCreate(subject="Post the reply", activeForm="Posting reply")`
7. `TaskCreate(subject="Create a ticket", activeForm="Creating ticket")`
8. `TaskCreate(subject="Mention ticket in thread", activeForm="Posting ticket link")`

Tasks 7–8 are conditional:
- `fix-warrants-ticket`: true when the fix is non-trivial, affects
  production/staging, or user explicitly requested a ticket
- `ticket-created`: true after a ticket is successfully created in Step 7

**PR review mode:**
1. `TaskCreate(subject="Parse Slack URL", activeForm="Parsing URL")`
2. `TaskCreate(subject="Read the thread", activeForm="Reading thread")`
3. `TaskCreate(subject="Delegate to PR review", activeForm="Reviewing PR")`

Set dependencies and update status as each completes.

## Overview

Given a Slack thread URL, read the report, root-cause it in the codebase,
post a technical reply with GitHub links, and optionally create a Linear ticket.

**PR review requests:** When the Slack thread contains a GitHub PR link and the
request is to review it or check its status, invoke the `pr:review` skill with
the PR URL instead of following Steps 3–6. Steps 1–2 (parse URL, read thread)
still apply to get context before delegating.

**External dependency:** `pr:review` is a user-level skill (installed at
`~/.claude/skills/pr-review/`). If unavailable, fall back to
`Dev10x:gh-pr-review` for PR review functionality.

## Workflow

### Step 1 — Parse the Slack URL

```bash
read channel_id thread_ts < <(${CLAUDE_PLUGIN_ROOT}/skills/investigate/scripts/parse-slack-url.sh "<url>")
```

URL format: `https://example.slack.com/archives/<CHANNEL_ID>/p<TIMESTAMP>`

### Step 2 — Read the Thread

Use MCP `slack_read_thread` with the channel_id and thread_ts.
Read all replies too — the answer may already be in the thread.

### Step 3 — Investigate the Codebase

Use a `Task` agent (`subagent_type: Explore`) with a focused prompt:
- What causes the symptom described?
- Which file/function is the proximate source?
- Are other call-sites affected?

For frontend display bugs look at:
- Formatting utilities (`formatCurrency`, `formatDate`, etc.)
- GraphQL fragments for nullable fields
- The component rendering the bad value

For backend errors look at:
- Model methods, serializers, signal handlers
- Recent migrations or model changes

### Step 4 — Verify Findings

Read the identified files directly to confirm line numbers and exact code before
drafting the reply. Wrong line numbers embarrass more than no links at all.

### Step 5 — Draft the Reply

Structure:
```
[1-sentence root cause summary]

[2-3 sentences of causal chain — backend → API → frontend]

[Fix description: what needs to change and where]
```

Slack link format: `<https://github.com/…/file.ts#L42|filename.ts#L42>`

GitHub repo mapping:
| Codebase | Repo |
|----------|------|
| app-admin | `https://github.com/example-org/example-admin` |
| app-pos | `https://github.com/example-org/app-pos` |
| app-backend | `https://github.com/example-org/example-backend` |

Use branch `develop` unless investigating a specific release.

**Formatting rules:**
- Slack does NOT render `[text](url)` — use `<url|text>` instead
- No markdown tables — use code blocks if tabular data is needed
- `*bold*` (single asterisks), `` `code` ``, `>quote`

### Step 6 — Post the Reply

```bash
${CLAUDE_PLUGIN_ROOT}/skills/investigate/scripts/reply.sh "$channel_id" "$thread_ts" "<message>"
```

Show the draft to the user and wait for approval before posting unless they
explicitly said to post immediately (e.g. "investigate and post").

### Step 7 — Create a Ticket (when warranted)

Create a ticket when:
- The fix is not trivial (more than changing one guard clause)
- The issue affects users in production or staging
- The user asks for one (e.g. "scope a ticket")

Invoke `Dev10x:ticket-create` skill with the gathered context.

### Step 8 — Mention the Ticket in the Thread

After ticket creation, post a follow-up reply:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/investigate/scripts/reply.sh "$channel_id" "$thread_ts" \
  "Logged as <https://linear.app/example/issue/PAY-XXX|PAY-XXX>."
```

## Common Mistakes

| Mistake | Consequence |
|---------|-------------|
| Using `[text](url)` Slack links | Links render as plain text — no one can click them |
| Posting line numbers without re-reading the file | Wrong line numbers undermine credibility |
| Skipping user approval before posting | Message goes out with errors you can't take back |
| Creating a ticket for a one-liner fix | Ticket noise, distracts the team |
| Not reading thread replies | Duplicating investigation someone already did |
| Using this skill for a Sentry URL with a domain-specific error | This skill is for Slack threads. If the Sentry error is about Square Terminal or payments, use `app-debug-payments` or `app-debug-payments` instead — they have pre-built SQL, decision trees, and scripts for those errors |
