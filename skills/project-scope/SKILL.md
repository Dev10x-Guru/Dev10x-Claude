---
name: Dev10x:project-scope
description: >
  Scope a multi-ticket project with milestones, blocking relationships,
  and tracker integration. Accepts a parent ticket URL/ID or free-text
  description and creates the full project structure in Linear, JIRA,
  or GitHub Issues.
  TRIGGER when: scoping a multi-ticket project with milestones and
  blocking relationships.
  DO NOT TRIGGER when: scoping a single ticket (use Dev10x:ticket-scope),
  or creating individual tickets (use Dev10x:ticket-create).
user-invocable: true
invocation-name: Dev10x:project-scope
allowed-tools:
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__save_issue
  - mcp__claude_ai_Linear__save_project
  - mcp__claude_ai_Linear__get_project
  - mcp__claude_ai_Linear__list_projects
  - mcp__claude_ai_Linear__save_milestone
  - mcp__claude_ai_Linear__list_milestones
  - mcp__claude_ai_Linear__list_issue_statuses
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - Bash(gh issue create:*)
  - Bash(gh label create:*)
  - Bash(gh api repos/:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Skill(Dev10x:ticket-create)
  - Bash(gh issue view:*)
  - Bash(gh issue edit:*)
  - Bash(gh api:*)
  - mcp__plugin_Dev10x_cli__detect_tracker
---

# Project Scope - Multi-Ticket Project Creation

## Overview

This skill orchestrates multi-ticket project creation with milestones
and blocking relationships. It takes a parent ticket or free-text
description and produces a complete project structure in the tracker.

**Use when:**
- Scoping a feature that spans multiple tickets and milestones
- Breaking down an epic or ADR into implementation phases
- Creating a project with blocking chains between tickets

**Do NOT use for:**
- Single-ticket scoping (use `Dev10x:ticket-scope`)
- Architectural decisions without implementation tickets (use `Dev10x:adr`)
- Creating a single ticket (use `Dev10x:ticket-create`)

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard).

**Auto-advance:** Complete each phase and immediately start the next.
Never pause between phases to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Gather & understand input", activeForm="Gathering context")`
2. `TaskCreate(subject="Scope project structure", activeForm="Scoping project")`
3. `TaskCreate(subject="Create tracker structure", activeForm="Creating structure")`
4. `TaskCreate(subject="Verify & report results", activeForm="Verifying entities")`

Set sequential dependencies: scope blocked by gather, create blocked
by scope, verify blocked by create.

## Input Classification

| Input | Type | Behavior |
|-------|------|----------|
| `PAY-662` or `JIRA-123` | Ticket ID | Call `detect_tracker` MCP tool, fetch as parent |
| `https://linear.app/.../issue/XXX-N/...` | Linear URL | Extract ID, fetch as parent |
| `https://*.atlassian.net/browse/XX-N` | JIRA URL | Extract ID, fetch as parent |
| `https://github.com/.../issues/N` | GitHub URL | Extract repo + number, fetch as parent |
| Free text description | New project | Create parent ticket first |

## Phase 1: Gather & Understand

### 1.1 Classify Input

Determine whether the user provided a ticket reference or free text.

### 1.2 Fetch Context

**If ticket reference:** Fetch ticket details (title, description,
comments, labels, related tickets) via Linear MCP or GitHub CLI.

**If free text:** Store as project description for Phase 2.

### 1.3 Detect Tracker

Call `mcp__plugin_Dev10x_cli__detect_tracker(ticket_id="$TICKET_ID")`
to determine the project's tracker backend.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-tracker-selection.md](./tool-calls/ask-tracker-selection.md)) when
tracker cannot be detected automatically (e.g., free-text input
with no branch context). Options:
- Linear (Recommended) — Create Linear project with milestones
- JIRA — Create JIRA epic with sub-tasks
- GitHub Issues — Create milestones and issues via `gh` CLI

### 1.4 Research Codebase

If the project involves code changes, explore the codebase for
relevant patterns, existing components, and architectural context.

## Phase 2: High-Level Scope

### 2.1 Produce Scope Document

Generate the following sections:

1. **Executive summary** — 1-2 paragraphs describing the project goal
   and approach
2. **Milestones** — named phases with goals and ordering
3. **Tickets per milestone** — title, 1-2 sentence description,
   priority, estimated complexity
4. **Blocking chain** — which tickets block which and why

Tickets are intentionally high-level. Further refinement via
`Dev10x:ticket-scope` is expected for individual tickets.

### 2.2 Present for Approval

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-scope-approval.md](./tool-calls/ask-scope-approval.md)).
This blocks execution until the user responds. Options:
- Approve (Recommended) — Create milestones and tickets as shown
- Revise — I have corrections to the structure
- More research needed — Need to explore additional areas

If "Revise": incorporate feedback and re-present.
If "More research": return to Phase 1.4 with user guidance.

## Agent Delegation (Phases 3-4)

**REQUIRED:** Delegate Phases 3 and 4 to a single background
haiku agent. Raw tracker API responses consume ~26k tokens for
a 6-issue project — the agent absorbs them and returns only a
compact summary.

**Dispatch after Phase 2 approval:**

1. Compose the agent prompt with:
   - Tracker type and configuration (team UUID, project UUID)
   - The full approved scope (milestones, tickets, blocking chain)
   - Creation instructions from Phase 3 below
   - Verification instructions from Phase 4 below

2. Dispatch:

```
Agent(
    subagent_type="general-purpose",
    model="haiku",
    description="Create {tracker} structure for {project}",
    prompt="<composed from approved scope + Phase 3-4 instructions>",
    run_in_background=true
)
```

3. When the agent completes, present its compact summary to the
   user. The main session never sees raw API response bodies.

**Agent return format (include verbatim in the prompt):**

```
Return ONLY a compact summary (max 200 words):
- Parent ticket: ID + URL
- Project entity: ID + URL (or "skipped")
- Per milestone: name → ID
- Per ticket: ID → URL → milestone
- Blocking chain: confirmed/failed pairs
- Failures: entity + reason + remediation
Do NOT return full API response bodies or descriptions.
```

Phases 3 and 4 below describe what the agent executes — include
the relevant instructions in the agent's prompt.

---

## Phase 3: Create Structure

### 3.1 Tracker Dispatch

| Operation | Linear | JIRA | GitHub Issues |
|-----------|--------|------|---------------|
| Create project | `save_project` (optional) | Epic via `Dev10x:jira` | N/A (use milestones) |
| Create milestone | `save_milestone` | Sprint/Fix Version via `Dev10x:jira` | `gh api repos/{owner}/{repo}/milestones --method POST` |
| Create label | (via `save_issue`) | (via `Dev10x:jira`) | `gh label create` |
| Create ticket | `save_issue` + milestone + project | via `Dev10x:jira` | `gh issue create --milestone --label --body-file` |
| Set blocking | `save_issue` blockedBy/blocks | Link via `Dev10x:jira` | Cross-reference in issue body (no native blocking) |

### 3.2 Create/Resolve Parent Ticket

**If free text:** Invoke `Skill(skill="Dev10x:ticket-create")` to
create the parent ticket using the executive summary as description.

**If ticket reference:** Use the fetched ticket as parent.

### 3.3 Create Project Entity (Optional)

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-project-entity.md](./tool-calls/ask-project-entity.md)).
This blocks execution until the user responds. Options:
- Create project entity (Recommended) — Enables roadmap views and project tracking
- Skip — Just milestones and tickets, no project entity

**After creating or selecting a project**, resolve its UUID
immediately via `list_projects(team: "TEAM_UUID")` and store
it for all subsequent calls. Never pass a project name or slug
to `save_issue` — name matching is exact and fails silently.
See `Dev10x:linear` § Project Assignment for the full pattern.

### 3.4 Create Milestones

Create milestones sequentially (tickets reference them by ID).
Check for existing milestones by name before creating to avoid
duplicates.

### 3.5 Create Tickets

Create all tickets with milestone and project assignments.
Use the project UUID resolved in 3.3 — never pass a display name.
Batch creation is possible since all milestones exist at this point.
Check for existing tickets by title before creating.

**GitHub Issues batch pattern (10+ issues):**

When creating many issues, use a sidecar metadata pattern to keep
issue bodies clean and reduce permission friction:

1. Create a temp directory for the batch:
   ```bash
   BATCH_DIR=$(/tmp/Dev10x/bin/mktmp.sh -d gh-issues batch)
   ```
2. For each issue, write two files via the Write tool:
   - `$BATCH_DIR/NNN-slug.md` — clean body content only
   - `$BATCH_DIR/NNN-slug.vars` — metadata:
     ```bash
     TITLE="Ticket title here"
     MILESTONE="Milestone Name"
     LABELS="enhancement,area/payments"
     ```
3. Create issues by iterating inline (no temp script):
   ```bash
   for vars in $BATCH_DIR/*.vars; do
     source "$vars"
     body="${vars%.vars}.md"
     gh issue create --repo "$REPO" --title "$TITLE" \
       --body-file "$body" --milestone "$MILESTONE" --label "$LABELS"
   done
   ```

This pattern was discovered in a session creating 36 issues — a single
loop approval replaced 36 individual `gh issue create` approvals.

**Anti-patterns to avoid (permission friction):**

- Do NOT use command substitution in `gh` commands:
  `gh issue edit --body "$(gh issue view ... | sed ...)"` — the `$()` breaks
  allow-rule prefix matching. Instead, write the body to a temp file first
  via Write tool, then `gh issue edit --body-file /tmp/file.md`.
- Do NOT prefix `gh` commands with env var assignments:
  `REPO="owner/repo" gh issue create ...` — the env prefix shifts the command
  prefix. Use `--repo owner/repo` inline instead.

### 3.6 Set Blocking Relationships

Set blocking/blocked-by relationships between tickets per the
approved blocking chain. Execute in parallel since all tickets exist.

### 3.7 Link Tickets to Project

Link all tickets to the project entity (if created in 3.3).
Execute in parallel.

## Phase 4: Verify & Report

### 4.1 Re-Fetch and Verify Linkage

Re-fetch all created entities to verify:
- Milestones are assigned correctly
- Blocking chains are intact
- Project links are set — for each ticket, call
  `get_issue(id)` and confirm `projectId` matches the
  expected UUID. Report any mismatches as failures in 4.3.

### 4.2 Structured Summary

Present a summary with:
- Parent ticket link
- Project entity link (if created)
- Milestone list with ticket counts
- Blocking chain visualization
- Links to all created tickets

### 4.3 Failure Reporting

Report any failures with:
- Which entity failed and why
- What succeeded (no rollback)
- Suggested manual remediation steps

## Error Handling

| Scenario | Behavior |
|----------|----------|
| API failure | Retry once, then report with failed entity details |
| Partial creation | Report what succeeded, do not roll back |
| Duplicate detected | Skip creation, use existing entity, log warning |
| Relationship failure | Log and continue with remaining relationships |

## Integration with Other Skills

| Trigger | Skill | Direction |
|---------|-------|-----------|
| Free-text needs parent ticket | `Dev10x:ticket-create` | Delegates to |
| Parent needs Job Story | `Dev10x:jtbd` | Delegates to (optional) |
| User refines a child ticket | `Dev10x:ticket-scope` | User invokes manually |
| User starts work on a ticket | `Dev10x:work-on` | User invokes manually |

Child tickets are NOT auto-scoped via `Dev10x:ticket-scope`.
High-level fidelity is intentional.
