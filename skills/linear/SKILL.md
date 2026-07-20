---
name: Dev10x:linear
invocation-name: Dev10x:linear
description: >
  Linear issue tracker operations via MCP tools. Get, create, update
  issues and list comments. Documentation-only skill — no scripts.
  TRIGGER when: performing CRUD operations on Linear issues, comments,
  or statuses.
  DO NOT TRIGGER when: using GitHub Issues or JIRA (use Dev10x:jira),
  or creating tickets across trackers (use Dev10x:ticket-create).
user-invocable: false
allowed-tools:
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__list_issues
  - mcp__claude_ai_Linear__save_issue
  - mcp__claude_ai_Linear__list_comments
  - mcp__claude_ai_Linear__create_comment
  - mcp__claude_ai_Linear__list_issue_statuses
  - mcp__claude_ai_Linear__get_issue_status
  - mcp__claude_ai_Linear__list_issue_labels
  - mcp__claude_ai_Linear__create_issue_label
  - mcp__claude_ai_Linear__save_project
  - mcp__claude_ai_Linear__get_project
  - mcp__claude_ai_Linear__list_projects
  - mcp__claude_ai_Linear__save_milestone
  - mcp__claude_ai_Linear__get_milestone
  - mcp__claude_ai_Linear__list_milestones
---

# Dev10x:linear — Linear Issue Tracker

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Linear issue operation", activeForm="Operating on Linear issue")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

Documentation-only skill centralizing Linear MCP tool references.
No scripts — all operations use MCP tools directly.

## Operation Mapping

| Operation | MCP Tool | Parameters |
|-----------|----------|------------|
| Get issue | `mcp__claude_ai_Linear__get_issue` | `id: "TEAM-133"` |
| List issues | `mcp__claude_ai_Linear__list_issues` | `team: "your-team-uuid"` |
| Create/update issue | `mcp__claude_ai_Linear__save_issue` | `id: "TEAM-133", state: "In Progress"` |
| List comments | `mcp__claude_ai_Linear__list_comments` | `issueId: "TEAM-133"` |
| Create comment | `mcp__claude_ai_Linear__create_comment` | `issueId: "TEAM-133", body: "..."` |
| List statuses | `mcp__claude_ai_Linear__list_issue_statuses` | `team: "your-team-uuid"` |
| Get status | `mcp__claude_ai_Linear__get_issue_status` | `id: "STATUS_UUID"` |
| List labels | `mcp__claude_ai_Linear__list_issue_labels` | `team: "your-team-uuid"` |
| Create label | `mcp__claude_ai_Linear__create_issue_label` | `team: "your-team-uuid", name: "label"` |
| Create/update project | `mcp__claude_ai_Linear__save_project` | `name: "Project", teamIds: ["UUID"]` |
| Get project | `mcp__claude_ai_Linear__get_project` | `id: "PROJECT_UUID"` |
| List projects | `mcp__claude_ai_Linear__list_projects` | `team: "TEAM_UUID"` |
| Create/update milestone | `mcp__claude_ai_Linear__save_milestone` | `name: "Phase 1", projectId: "UUID"` |
| Get milestone | `mcp__claude_ai_Linear__get_milestone` | `id: "MILESTONE_UUID"` |
| List milestones | `mcp__claude_ai_Linear__list_milestones` | `projectId: "UUID"` |

## Team IDs

| Team | UUID |
|------|------|
| YOUR_TEAM | `your-team-uuid` |

Replace `your-team-uuid` with the UUID from your Linear workspace settings.
To find it: Settings → Teams → select your team → the UUID is in the URL.

## URL Template

```
https://linear.app/your-org/issue/{TICKET_ID}
```

Example: `https://linear.app/your-org/issue/TEAM-133`

Replace `your-org` with your Linear organization slug.

## Prerequisite Check

Before using Linear MCP tools, verify availability:

1. Check if any `mcp__claude_ai_Linear__*` or `mcp__plugin_linear_linear__*` tool is available
2. If not available, inform the user:
   ```
   Linear MCP is not enabled. Please enable the Linear MCP server
   in your Claude Code settings to use this skill.
   ```
3. Do not proceed if Linear MCP is unavailable

## Project Assignment

**CRITICAL: Always resolve project UUID before assignment.**
The `save_issue` `project` parameter accepts a name, ID, or slug —
but name matching is exact and **fails silently** on mismatch.
`"app-pos-mcp"` vs `"app-pos mcp"` will succeed without error but
leave the ticket unlinked.

### Resolution Steps

1. **Resolve UUID first** — call `list_projects(team: "TEAM_UUID")`
   and match by display name (case-insensitive, normalize hyphens
   to spaces)
2. **Use the UUID** in all subsequent `save_issue` calls:
   `save_issue(id: "TEAM-133", project: "PROJECT_UUID")`
3. **Verify linkage** — after `save_issue`, call
   `get_issue(id: "TEAM-133")` and confirm the response contains
   the expected `projectId`

### Batch Assignment Verification

After assigning multiple tickets to a project, verify all were
linked by calling `list_issues(project: "PROJECT_UUID")` and
checking that every expected ticket ID appears in the results.

## Searching for JTBD in Ticket

To find an existing Job Story on a Linear ticket:

1. Get issue: `mcp__claude_ai_Linear__get_issue(id: "TEAM-133")`
2. Search the description for `**When**` / `**I want to**` / `**so I can**` pattern
3. For localized tickets, also search for translated structural labels in
   the ticket language
4. If BDD or Gherkin-derived keywords appear, validate translations
   against Cucumber's language reference:
   https://cucumber.io/docs/gherkin/languages/
5. If not found, list comments: `mcp__claude_ai_Linear__list_comments(issueId: "TEAM-133")`
6. Search each comment body for the same pattern
7. Return the first match, or empty if none found

## MCP Tool Variants

Two MCP server configurations may provide Linear tools:

| Provider | Tool prefix | Notes |
|----------|-------------|-------|
| Claude AI (cloud) | `mcp__claude_ai_Linear__` | Available in Claude Code web/desktop |
| Plugin (local) | `mcp__plugin_linear_linear__` | Requires local MCP server config |

Both provide the same operations. Check for either prefix when
verifying availability.
