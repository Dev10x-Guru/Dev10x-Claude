---
name: Dev10x:ticket-create
description: >
  Create an issue tracker ticket (GitHub issue, Linear, or JIRA) with
  proper formatting, description structure, and labels. Accepts title,
  description content, and optional labels. Automatically formats the
  description with Root Cause, Solution, and Files Changed sections.
  Returns the created ticket ID.
  TRIGGER when: a new ticket needs to be created for tracking work.
  DO NOT TRIGGER when: ticket already exists (use Dev10x:ticket-scope
  to enrich it), or user wants to update an existing ticket.
user-invocable: true
invocation-name: Dev10x:ticket-create
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/ticket-create/scripts/:*)
  - Bash(gh issue create:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - mcp__claude_ai_Linear__save_issue
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__list_projects
  - Bash(secret-tool lookup:*)
  - Bash(curl:*atlassian.net*)
---

# Create Issue Tracker Ticket

## Overview

This skill creates a well-structured ticket in GitHub Issues, Linear, or JIRA with proper formatting, comprehensive description, and appropriate labels. It ensures consistent ticket quality across all creation contexts.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create issue tracker ticket", activeForm="Creating ticket")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Prerequisites Check

Determine which tracker to use. Priority:

1. **Explicit argument** — user specifies `--github`, `--linear`, or `--jira`
2. **detect_tracker MCP tool** — if a ticket prefix is available (from branch
   name), call `mcp__plugin_Dev10x_cli__detect_tracker` to match the project's
   tracker
3. **Repo default** — if no prefix, check autolinks to determine project's
   primary tracker. GitHub Issues if no autolinks exist.

**Fast-fail rule:** Make ONE attempt at the `detect_tracker` MCP call.
If the tool is unavailable, returns an error, or `ToolSearch` does not
surface it on the first lookup, fall through to step 3 (repo default)
immediately. Do NOT retry `ToolSearch` for Linear, JIRA, or
`detect_tracker` MCP names. Repeated retries block the skill for
many minutes and produce no new information — the absence of a tool
on the first lookup means it is not registered in this session.

| Tracker | Required | Creation method |
|---------|----------|----------------|
| GitHub | `gh` CLI | `gh issue create` |
| Linear | Linear MCP | `mcp__claude_ai_Linear__save_issue` |
| JIRA | `JIRA_TENANT` + keyring | Delegate to `Dev10x:jira` skill |

## When to Use This Skill

Use this skill when:
- Creating a ticket for tech debt that needs tracking
- Converting an untracked change into a formal ticket
- Creating a bug report ticket
- Documenting an improvement or enhancement
- Need a properly structured ticket with consistent formatting

## Input Requirements

This skill requires:
1. **Context** - Information about the problem/improvement (can be from a commit, code analysis, or user description)
2. **Optional: Title** - If not provided, generate from context.
   When `--body-file` is used without `--title`, the first line
   of the file is used as the title (separated from the body by
   a blank line). This avoids permission friction from special
   characters in args strings.
3. **Optional: Labels** - If not provided, infer from context

## Workflow

### Step 1: Analyze Context

Understand what the ticket is about from the provided context:

**Context can come from:**
- Git commit diff and message (`git show <commit-hash>`)
- Code files that need improvement
- User description of the problem
- Bug report or issue description

**Extract:**
- What problem is being solved?
- Why did the issue exist?
- What changes were/will be made?
- What files are affected?

### Step 2: Generate Ticket Title

Create a descriptive, concise title following these patterns:

**Title Format Patterns:**

| Context | Pattern | Example |
|---------|---------|---------|
| Tech debt | "Fix tech debt in..." | "Fix tech debt in TestAddTireService flaky tests" |
| Bug fix | "Fix bug in..." | "Fix bug in payment processing timeout handling" |
| Enhancement | "Improve..." | "Improve customer search performance" |
| Refactoring | "Refactor..." | "Refactor invoice generation service" |
| Test improvement | "Fix flaky test in..." | "Fix flaky test in work order creation" |
| Missing feature | "Add..." | "Add retry mechanism for Square API" |

**Title Rules:**
- Keep concise but descriptive (aim for < 80 characters)
- Start with action verb (Fix, Improve, Add, Refactor, etc.)
- Be specific about the component/area affected
- Avoid vague terms like "issue" or "problem" without context
- **Describe the user-facing outcome, not the implementation detail.** E.g., `Enable automatic terminal discovery` not `Add DEVICES_READ to Square OAuth scopes`

### Step 3: Generate Description

Create a comprehensive description using this structure:

**Structure:**
```markdown
<Brief 1-2 sentence summary of the problem/improvement>

## Root Cause
- <Primary reason the issue existed>
- <Contributing factors>
- <Technical details about why this happened>

## Solution
- <First key change or improvement>
- <Second key change or improvement>
- <Third key change or improvement>
- <Additional changes as needed>

## Files Changed
- <file path 1> - <what changed>
- <file path 2> - <what changed>
- <file path 3> - <what changed>
```

### Step 4: Determine Labels

Select appropriate labels based on the context:

**Available Labels:**

| Label | When to Use |
|-------|-------------|
| `tech-debt` | Technical improvements, refactoring, code quality issues |
| `bug` | Production bugs, incorrect behavior, errors |
| `testing` | Test improvements, test infrastructure, test coverage |
| `flaky-tests` | Tests that fail intermittently. **Always use for flaky test tickets** alongside `Bug` |
| `performance` | Performance optimizations, slow queries |
| `documentation` | Documentation updates, missing docs |
| `security` | Security vulnerabilities, auth issues |

### Step 5: Create the Ticket

**REQUIRED: Dispatch a background haiku agent to create the ticket.**
Execute this `Agent` call (do NOT inline ticket creation in the main
session). This prevents raw API responses (full issue JSON, project
lookups) from consuming main session context — the agent returns only
the ticket ID and URL.

1. `Agent(subagent_type="general-purpose", model="haiku", description="Create {tracker} ticket: {short_title}", prompt="<see template below>", run_in_background=true)`

The agent prompt template (substitute placeholders before dispatching):

```
Create a ticket with the following details:

Tracker: {tracker_type}
Title: {title}
Description: {description}
Labels: {labels}
{tracker-specific config: team UUID, project UUID, repo}

{include the tracker-specific instructions below}

Return ONLY:
- Tracker: {GitHub Issues | Linear | JIRA}
- ID: {ticket ID}
- URL: {ticket URL}
Do NOT return full API response bodies.
```

The main session waits for the agent result and passes it to
Step 6. The tracker-specific instructions below describe what
the agent executes — include the relevant section in the agent's
prompt (the fenced blocks under each tracker are reference material
for the dispatched agent, not instructions for the main session).

**Nested invocation:** When invoked from a background agent
(e.g., from `project-scope`'s Phase 3 agent), skip the
delegation wrapper and execute creation directly. Detection:
if the skill is running as a Skill() call within an Agent()
prompt (vs. in main session), this SKILL.md is your read
context — your caller (the agent prompt) already optimizes
the session context, so you execute creation directly per
tracker-specific instructions below without wrapping in
Agent().

**Tracker-specific creation instructions:**

Dispatch to the detected tracker:

**GitHub Issues:**

Write the description to a temp file first (inline `--body` strings
break shell quoting on markdown tables and long descriptions):
```bash
# Generate temp path via mktmp.sh, then write body via Write tool
BODY_FILE=$(/tmp/Dev10x/bin/mktmp.sh gh-issue body .md)
# Write description content to $BODY_FILE via the Write tool
gh issue create --repo "$REPO" --title "$TITLE" --body-file "$BODY_FILE" --label "$LABELS"
```

**Title-in-file convention:** When the caller provides
`--body-file` without `--title`, use the wrapper script that
reads line 1 as the title and creates the issue in one call
(like `git commit -F`):
```bash
${CLAUDE_PLUGIN_ROOT}/skills/ticket-create/scripts/create-github-issue.sh "$BODY_FILE" "$REPO" "$LABELS"
```
This avoids passing titles with special characters in args
strings, which can cause permission friction.

**Linear:**

If a `project` parameter was provided by the caller, resolve the
project UUID first via `list_projects(team: "TEAM_UUID")` — never
pass a display name (name matching is exact and fails silently).
After creation, verify linkage with `get_issue(id)` and confirm
`projectId` matches the expected UUID. See `Dev10x:linear`
§ Project Assignment.

```
mcp__claude_ai_Linear__save_issue(
    team: "TEAM_UUID",
    title: TITLE,
    description: DESCRIPTION,
    labels: [LABELS],
    project: "PROJECT_UUID"  # optional — resolved UUID only
)
```

**JIRA:**

Delegate to the `Dev10x:jira` skill:

```
Skill(skill="Dev10x:jira")
```

Pass the ticket ID and payload path as arguments.

> Team-specific IDs are documented in the tracker skill (`Dev10x:linear`, `Dev10x:jira`).

### Step 6: Return Ticket Information

Extract and return the ticket details:

```
Ticket Created

Tracker: {GitHub Issues | Linear | JIRA}
ID: {GH-42 | PAY-519 | JIRA-1234}
Title: {title}
URL: {tracker-specific URL}
```

## Important Notes

- Keep titles concise but descriptive
- Always include Root Cause, Solution, and Files Changed sections
- Apply relevant labels to improve discoverability
- Return the ticket ID for use in subsequent workflows
- Don't modify ticket after creation unless explicitly asked

## Integration with Other Skills

This skill is designed to be used by other skills:

- **commit:to-new-ticket**: Uses this skill in Step 3 to create ticket from commit
- **test:fix-flaky**: Uses this skill in Step 3 to create tech debt ticket
- **Standalone usage**: User manually creates ticket with provided context
