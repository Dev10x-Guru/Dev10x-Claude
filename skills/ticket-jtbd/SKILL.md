---
name: Dev10x:ticket-jtbd
description: >
  Write a JTBD Job Story and apply it to a target (PR description,
  GitHub issue, Linear ticket, or JIRA ticket). Delegates drafting to
  the Dev10x:jtbd base skill, then handles the side-effecting write.
  TRIGGER when: a ticket or PR needs a Job Story written or updated.
  DO NOT TRIGGER when: JTBD is already present in the target, or user
  is writing commit messages (use Dev10x:git-commit for that).
user-invocable: true
invocation-name: Dev10x:ticket-jtbd
allowed-tools:
  - Bash(gh pr view:*)
  - Bash(gh pr diff:*)
  - Bash(gh pr edit:*)
  - Bash(gh pr list:*)
  - Bash(git log:*)
  - Bash(git diff:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__list_issues
  - mcp__claude_ai_Linear__list_comments
  - mcp__claude_ai_Linear__create_comment
  - mcp__claude_ai_Linear__update_issue
  - Bash(secret-tool lookup:*)
  - Bash(curl:*atlassian.net*)
  - Bash(gh issue comment:*)
  - mcp__plugin_Dev10x_cli__detect_tracker
---

# Write JTBD Story to Target

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Write JTBD Job Story", activeForm="Writing Job Story")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

This skill drafts a JTBD Job Story using the `Dev10x:jtbd` base skill and
then writes the approved story to a target: PR description, GitHub
issue, Linear ticket description, or JIRA ticket.

## When to Use This Skill

- After creating a PR, to add business context before requesting review
- When preparing PRs for release notes collection
- When a PR or ticket description needs a user-facing summary
- Called by `pr:monitor` in Phase 0 when a PR is missing its Job Story

## Input

Accepts one or both of:
- **PR URL or number** — e.g., `1167` or `https://github.com/example-org/app-pos/pull/1167`
- **Linear ticket URL or ID** — e.g., `PAY-519` or `https://linear.app/example/issue/PAY-519/...`
- **GitHub issue ID** — e.g., `GH-15`

If only one is provided, infer the other:
- PR → extract ticket ID from branch name
- Ticket → find linked PR from ticket attachments

## Workflow

### Step 1: Auto-Detect Target

Determine the write target from the arguments:

| Argument | Target |
|----------|--------|
| PR number or URL | PR description |
| GitHub issue ID (GH-xxx) | GitHub issue (posted as comment) |
| Linear ticket ID (PAY-xxx) | Linear ticket description |
| JIRA ticket ID (JIRA-xxxx) | JIRA ticket description |
| Both PR + ticket | PR description (primary), ticket as context source |

### Step 2: Gather Identifiers

Extract all available identifiers for context:

```bash
# If PR provided, extract ticket ID from branch
gh pr view {PR_NUMBER} --json headRefName -q '.headRefName' | cut -d'/' -f2

# If ticket provided, find linked PR
gh pr list --search "{TICKET_ID}" --state open --json number --limit 1
```

### Step 3: Delegate to Dev10x:jtbd Base Skill

Invoke the `Dev10x:jtbd` skill in **attended mode** with all available context:

- `ticket_id`: extracted ticket ID
- `pr_number`: extracted PR number
- `mode`: attended

The `Dev10x:jtbd` skill handles all context gathering, situation
identification, and draft presentation. It returns the approved
story string (or empty if user rejects).

### Step 4: Write to Target

If the user approved the story (non-empty return):

**PR description target:**
Write the updated body to a temp file (include PR# to avoid clashes),
then use `--body-file`:

1. Use the Write tool to create `/tmp/Dev10x/pr-body-{PR_NUMBER}.md`
   with the Job Story prepended to the existing body
2. Run: `gh pr edit {PR_NUMBER} --repo {REPO} --body-file /tmp/Dev10x/pr-body-{PR_NUMBER}.md`

The story goes at the **top** of the description so it's the first
thing visible in PR lists and Slack previews.

**GitHub issue target:**
Post the Job Story as a comment on the GitHub issue:

1. Call the MCP tool to get the repo and number:
   `mcp__plugin_Dev10x_cli__detect_tracker(ticket_id="$TICKET_ID")`
2. Post the comment:
   `gh issue comment "$TICKET_NUMBER" --repo "$REPO" --body "$JOB_STORY"`

**Linear ticket target:**
Prepend the Job Story to the existing ticket description:

```
mcp__claude_ai_Linear__update_issue(
  id: "{TICKET_ID}",
  description: "{job_story}\n\n{existing_description}"
)
```

**JIRA ticket target:**
Delegate to the `Dev10x:jira` skill for JIRA updates.

1. Use the Write tool to create `/tmp/Dev10x/jira-payload-{TICKET_ID}.json`
   with the JIRA REST API v3 ADF document format
2. Invoke `Skill(skill="Dev10x:jira")` to apply the payload to the ticket

### Step 5: Confirm

```
Updated {target_type} with Job Story.
{target_url}
```

## Usage Modes

| Caller | Dev10x:jtbd Mode | Write Target |
|--------|-----------|-------------|
| Standalone `/Dev10x:ticket-jtbd 1167` | attended | PR description |
| Standalone `/Dev10x:ticket-jtbd PAY-519` | attended | Linear ticket |
| Standalone `/Dev10x:ticket-jtbd GH-15` | attended | GitHub issue (comment) |
| `pr:monitor` Phase 0 | attended | PR description |

## Examples

### Example 1: Write to PR

**Input:** `/Dev10x:ticket-jtbd 1167`

1. Auto-detect: PR number → target is PR description
2. Extract ticket ID from branch: `PAY-519`
3. Delegate to `Dev10x:jtbd` (attended) → user approves draft
4. Prepend story to PR #1167 description
5. Confirm: `Updated PR #1167 with Job Story.`

### Example 2: Write to Linear ticket

**Input:** `/Dev10x:ticket-jtbd PAY-519`

1. Auto-detect: Linear ticket ID → target is Linear ticket
2. Find linked PR (if any) for additional context
3. Delegate to `Dev10x:jtbd` (attended) → user approves draft
4. Prepend story to PAY-519 description
5. Confirm: `Updated PAY-519 with Job Story.`

### Example 3: Both PR and ticket

**Input:** `/Dev10x:ticket-jtbd 1167 PAY-519`

1. Auto-detect: PR + ticket → primary target is PR description
2. Delegate to `Dev10x:jtbd` (attended) with both identifiers
3. Prepend story to PR #1167 description
4. Confirm: `Updated PR #1167 with Job Story.`

### Example 4: Write to GitHub issue

**Input:** `/Dev10x:ticket-jtbd GH-15`

1. Auto-detect: `GH-` prefix → target is GitHub issue
2. Fetch issue body and comments for context
3. Delegate to `Dev10x:jtbd` (attended) → user approves draft
4. Post story as comment on GH-15
5. Confirm: `Updated GH-15 with Job Story.`

## Integration with Other Skills

```
Dev10x:ticket-jtbd
├── Delegates to: Dev10x:jtbd (pure base — context gathering + drafting)
├── Called by: pr:monitor Phase 0 (when JTBD missing from PR)
└── Replaces: job-story (former monolithic skill)
```
